# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Composition root: the one place that wires ingest output → graph → retrieval.
The lanes never import each other; they meet here and in models/."""

from datetime import date

from graph.resolve import resolve
from ingest.gates import SourceUnavailable, read_source
from models.answer import Answer, EvidenceFilter, TimeFilter
from models.claim import ClaimRecord, ResolvedClaim
from retrieval.assemble import assemble
from settings import Settings


class IndexMissing(Exception):
    pass


class SpanDrift(Exception):
    pass


def resolve_span(path: str, start: int, end: int, expected_hash: str, cfg: Settings) -> str:
    """Citation pointer → verified text, wrapped as untrusted. Refuses on hash drift:
    a cited file that changed since ingest no longer proves the claim."""
    prefix = f"{cfg.corpus_dir}/"
    if not path.startswith(prefix):
        raise SpanDrift(f"{path} is not a corpus citation")
    try:
        source = read_source(
            cfg.corpus_root,
            cfg.resolve_path(cfg.diagram_transcripts_dir),
            path.removeprefix(prefix),
        )
    except SourceUnavailable as exc:
        raise SpanDrift(str(exc)) from exc
    if source.content_hash != expected_hash:
        raise SpanDrift(f"{path} changed since it was cited (hash mismatch)")
    if not 1 <= start <= end <= len(source.lines):
        raise SpanDrift(f"{path}:{start}-{end} is outside the file")
    text = "\n".join(source.lines[start - 1 : end]).replace("</untrusted_source", "&lt;/")
    return f'<untrusted_source path="{path}" lines="{start}-{end}">{text}</untrusted_source>'


def load_claims(cfg: Settings) -> list[ClaimRecord]:
    path = cfg.resolve_path(cfg.claims_path)
    if not path.is_file():
        raise IndexMissing(f"{path} not found — run `uv run ncs ingest` first")
    return [
        ClaimRecord.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def resolved(cfg: Settings, as_of: date) -> list[ResolvedClaim]:
    return resolve(load_claims(cfg), as_of, cfg)


def query(
    question: str,
    cfg: Settings,
    time: TimeFilter | None = None,
    evidence: EvidenceFilter | None = None,
) -> Answer:
    time = time or TimeFilter()
    as_of = time.as_of or date.today()
    return assemble(question, resolved(cfg, as_of), as_of, time, evidence or EvidenceFilter(), cfg)
