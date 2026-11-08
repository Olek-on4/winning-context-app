"""The diagram reader, on the real corpus file, without a graph or a network.

The gate from ADR-0012: a fact that exists only in a picture must come back from that
picture, with the rectangle it was read from. The blob is the real PNG, not a fixture, so
the test fails when the reader regresses rather than when a fixture drifts.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("rapidocr", reason="the diagram extra is not installed")

from ingest.diagram import DiagramText
from sources import Root

CORPUS = Path("../../vendor/att-hackathon-task")
ERD = CORPUS / "diagrams" / "customer-orders-erd.png"


def extract(path: Path) -> list:
    root = Root(id="att-hackathon-task", path=CORPUS.resolve(), kind=None)
    return list(DiagramText().extract(root, path.resolve(), "digest"))


def test_the_declared_type_is_read_from_the_pixels():
    claims = extract(ERD)
    typed = {c.subject.key: c.object for c in claims if c.predicate == "HAS_DECLARED_TYPE"}
    assert typed.get("orders.total") == "REAL (USD)", typed
    # `total_minor` is the current schema; only the picture still says REAL.
    assert all("minor" not in str(c.object) for c in claims)


def test_every_claim_cites_a_region_inside_the_bitmap():
    claims = extract(ERD)
    assert claims, "the ERD must yield claims"
    for claim in claims:
        span = claim.evidence[0]
        assert span.region is not None, "an image claim without a rectangle cannot be verified"
        assert span.start_line == span.end_line == 1
        assert span.region.x + span.region.w <= 1326
        assert span.region.y + span.region.h <= 581


def test_the_same_picture_yields_the_same_claims():
    first = sorted((c.claim_id, c.subject.key, str(c.object)) for c in extract(ERD))
    second = sorted((c.claim_id, c.subject.key, str(c.object)) for c in extract(ERD))
    assert first == second


def test_a_pixel_only_line_is_searchable_as_a_chunk_with_its_rectangle():
    """`Friday 16:00` is prose-absent and is not a declared type: it lives in the chunk."""
    from graph.chunks import _image_chunk

    root = Root(id="att-hackathon-task", path=CORPUS.resolve(), kind=None)
    rows = _image_chunk(root, Path("diagrams/people-finance-process.png"), "digest")
    assert rows, "the picture must become a chunk or it can never be searched"
    assert "16:00" in rows[0]["text"]
    assert rows[0]["region_w"] == 1205 and rows[0]["region_h"] == 812
    assert rows[0]["start_line"] == rows[0]["end_line"] == 1
