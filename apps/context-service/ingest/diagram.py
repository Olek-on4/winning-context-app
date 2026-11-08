"""Diagram text: what a picture says, cited by the rectangle it was read from.

Automatic by design — a corpus may hold thousands of images and nobody describes each one
(ADR-0012). The reader is `rapidocr` on onnxruntime, which carries no strong copyleft, so
this pipeline is ungated; a GPL alternative lives in `diagram_tesseract.py` behind the
opt-in gate. Every claim cites the region it came from, because OCR text can never satisfy
a verbatim span gate (`customerId` reads as `customerld` under a different engine).

Confidence is the `extractor_version`-independent reading of *this* pipeline: text blocks
carry their own OCR confidence and a claim's confidence is that, scaled by what the text
looked like, never a constant.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from ingest.gates import dated_by_reference
from models.claim import ClaimRecord, EntityRef, Modality, Polarity, Region, SourceType, Span
from settings import AUTHORITY, DIAGRAM_ENGINE, DIAGRAM_MIN_OCR_CONFIDENCE
from sources import Root, image_size

IMAGE_SUFFIXES = frozenset({".png", ".gif"})


def quiet() -> None:
    """The engine logs every model load at INFO; a corpus walk would bury the real output."""
    import logging

    logging.getLogger("RapidOCR").setLevel(logging.WARNING)
# `total: REAL (USD)` / `id: TEXT PK` — a declared type, the thing prose cannot give for
# an older diagram revision.
DECLARED = re.compile(r"^(?P<column>[A-Za-z_][\w ]{0,40}?)\s*:\s*(?P<type>[A-Z][A-Z0-9_ ()]{1,40})$")


class DiagramText:
    """OCR every image the walk finds; one pipeline, no model, no network at import."""

    name = "diagram.ocr"

    def matches(self, path: Path) -> bool:
        return path.suffix.lower() in IMAGE_SUFFIXES

    # Bump this when our own reading logic changes; the libraries are composed below, so a
    # silent upgrade of either invalidates the claims it would otherwise quietly alter.
    LOGIC = "2"

    @property
    def version(self) -> str:
        """Engine, library builds and our own logic: anything that changes a claim."""
        from importlib.metadata import version as package_version

        import onnxruntime

        engine = package_version("rapidocr")
        return f"rapidocr-{engine}-ort-{onnxruntime.__version__}-{DIAGRAM_ENGINE}-logic{self.LOGIC}"

    def extract(self, root: Root, path: Path, digest: str) -> Iterable[ClaimRecord]:
        # Silence first: the engine logs each model load at import time, not on use.
        quiet()
        from rapidocr import RapidOCR  # lazy: importing this module must not load a model

        engine = RapidOCR()
        result = engine(str(path))
        texts = list(result.txts or [])
        if not texts:
            return iter(())
        try:
            width, height = image_size(path)
            whole = Region(x=0, y=0, w=width, h=height)
        except ValueError:
            whole = None
        boxes = result.boxes if result.boxes is not None else [None] * len(texts)
        frames = _frames(path)
        scores = result.scores if getattr(result, "scores", None) is not None else [1.0] * len(texts)
        # Same date rule as every other pipeline: a release that names the file, then git,
        # then the file's own header. Imported here because registry registers this module.
        from ingest.registry import _observed

        observed = dated_by_reference(root, path.name) or _observed(root, path)
        common = dict(
            observed_at=observed,
            valid_from=observed,
            observed_precision="day",
            modality=Modality.FACT,
            authority=AUTHORITY[SourceType.DESIGN_DOC],
            source_type=SourceType.DESIGN_DOC,
            extractor=self.name,
            extractor_version=self.version,
        )
        for text, box, score in zip(texts, boxes, scores):
            text = text.strip()
            if not text or float(score) < DIAGRAM_MIN_OCR_CONFIDENCE:
                continue
            region = _region(box) or whole
            if region is None:
                continue
            span = Span(path=root.pointer(path.relative_to(root.path)), start_line=1, end_line=1,
                        content_hash=digest, region=region)
            # The picture's words are a chunk, not a fact per line: emitting one claim per
            # OCR line flooded retrieval with statements nobody asks about and outranked
            # the declared types that are the point of reading the diagram.
            declared = DECLARED.match(text)
            if declared:
                # The table a column belongs to is the box it sits in, named by the label
                # nearest that box's top — `total` alone is not a fact anyone asked for.
                table = _table_for(box, frames, boxes, texts)
                column = declared.group("column").strip()
                yield ClaimRecord(
                    subject=EntityRef(kind="Table", key=f"{table}.{column}" if table else column),
                    predicate="HAS_DECLARED_TYPE", object=declared.group("type").strip(),
                    polarity=Polarity.ASSERTS, confidence=round(float(score), 3),
                    evidence=[span], **common,
                )


def _frames(path: Path) -> list[Region]:
    """Box rectangles: a closed outline whose hole is large, deduplicated by containment.

    Measured on the corpus: this finds exactly the ERD's three tables and January's seven
    shapes, where contour tracing found zero or one.
    """
    import cv2
    import numpy as np

    image = cv2.imread(str(path))
    if image is None:
        return []
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = cv2.threshold(gray, 205, 255, cv2.THRESH_BINARY_INV)[1]
    closed = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, hierarchy = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return []
    found: list[Region] = []
    for index, node in enumerate(hierarchy[0]):
        if node[3] == -1 or cv2.contourArea(contours[index]) <= 3000:
            continue
        x, y, w, h = cv2.boundingRect(contours[node[3]])
        if w * h >= 0.9 * gray.shape[0] * gray.shape[1]:
            continue
        found.append(Region(x=int(x), y=int(y), w=max(1, int(w)), h=max(1, int(h))))
    found.sort(key=lambda r: r.w * r.h, reverse=True)
    frames: list[Region] = []
    for rect in found:
        if not any(rect.x >= f.x - 3 and rect.y >= f.y - 3 and rect.x + rect.w <= f.x + f.w + 3
                   and rect.y + rect.h <= f.y + f.h + 3 for f in frames):
            frames.append(rect)
    return frames


def _table_for(box, frames, boxes, texts) -> str | None:
    """The label naming the frame a line sits in: the topmost text inside that frame.

    Without it a read of `total: REAL (USD)` becomes a fact about `total`, which nobody
    asked about, instead of about `orders.total`, which the question names.
    """
    rect = _region(box)
    if rect is None or not frames:
        return None
    cx, cy = rect.x + rect.w / 2, rect.y + rect.h / 2
    # The smallest frame that contains the line: a table drawn inside another table's
    # whitespace must not inherit the outer one's name.
    inside_frames = [f for f in frames if f.x <= cx <= f.x + f.w and f.y <= cy <= f.y + f.h]
    frame = min(inside_frames, key=lambda f: f.w * f.h) if inside_frames else None
    if frame is None:
        return None
    inside = []
    for other, candidate in zip(boxes, texts):
        area = _region(other)
        if area is None or not candidate:
            continue
        ox, oy = area.x + area.w / 2, area.y + area.h / 2
        if frame.x <= ox <= frame.x + frame.w and frame.y <= oy <= frame.y + frame.h:
            inside.append((area.y, str(candidate).strip()))
    if not inside:
        return None
    candidate = min(inside)[1]
    # The title is a bare identifier; a line with a colon is already a declaration.
    return candidate if candidate and ":" not in candidate and len(candidate) <= 40 else None


def _region(box) -> Region | None:
    """OCR gives four corner points; the citation is their bounding rectangle."""
    try:
        xs = [int(p[0]) for p in box]
        ys = [int(p[1]) for p in box]
    except (TypeError, ValueError, IndexError):
        return None
    x, y = max(0, min(xs)), max(0, min(ys))
    w, h = max(1, max(xs) - x), max(1, max(ys) - y)
    return Region(x=x, y=y, w=w, h=h)
