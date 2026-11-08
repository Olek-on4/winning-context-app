"""A region citation: an image has no lines, so the pointer is a rectangle.

The legs the text gate runs (verbatim excerpt, relocated line) do not exist for a picture.
What replaces them is geometric: the rectangle must be inside the real bitmap and the file
must still be the one that was read.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from ingest.gates import verify
from models.claim import ClaimRecord, EntityRef, Polarity, Region, SourceType, Span
from retrieval.service import ContextService
from sources import Root, SpanStore, image_size

DIAGRAM = Path("../../vendor/att-hackathon-task/diagrams/customer-orders-erd.png")


def claim(span: Span, *, excerpt: str | None = None, predicate: str = "HAS", **kw) -> ClaimRecord:
    return ClaimRecord(
        subject=EntityRef(kind="Table", key="orders"),
        predicate=predicate,
        object="total: REAL (USD)",
        polarity=Polarity.ASSERTS,
        observed_at=dt.date(2026, 1, 1),
        valid_from=dt.date(2026, 1, 1),
        confidence=0.6,
        extractor="diagram.test",
        source_type=SourceType.DESIGN_DOC,
        evidence=[span],
        excerpt=excerpt,
        **kw,
    )


def region_span(path: str = "customer-orders-erd.png", x=100, y=50, w=200, h=40) -> Span:
    return Span(path=path, start_line=1, end_line=1, content_hash="", region=Region(x=x, y=y, w=w, h=h))


def store_with(path: Path = DIAGRAM) -> SpanStore:
    """A store whose single root is the corpus diagrams directory, like production."""
    return SpanStore([Root(id="att-hackathon-task", path=path.parent)])


def test_region_changes_the_claim_id_and_a_line_span_keeps_its_own():
    line = Span(path="docs/a.md", start_line=3, end_line=3, content_hash="h")
    a = claim(line, predicate="HAS_COLUMN")
    b = claim(region_span(), predicate="HAS_COLUMN")
    c = claim(region_span(x=101))
    assert a.claim_id != b.claim_id, "a rectangle is part of a claim's identity"
    assert b.claim_id != c.claim_id, "two places in one image are two claims"
    # the existing 311 ids depend on this: no region, no suffix
    assert a.claim_id == claim(line, predicate="HAS_COLUMN").claim_id


def test_a_region_span_cites_the_whole_file():
    with pytest.raises(ValueError, match="start_line and end_line must be 1"):
        Span(path="a.png", start_line=2, end_line=2, content_hash="h", region=Region(x=0, y=0, w=1, h=1))


@pytest.mark.parametrize("region", [dict(x=-1, y=0, w=1, h=1), dict(x=0, y=0, w=0, h=1), dict(x=0, y=0, w=1, h=0)])
def test_a_region_must_be_a_real_rectangle(region):
    with pytest.raises(ValueError):
        Region(**region)


def test_the_bitmap_size_comes_from_the_header_not_a_decoder():
    width, height = image_size(DIAGRAM)
    assert (width, height) == (1326, 581)


def test_a_region_claim_that_quotes_text_is_dropped_loudly(capsys):
    kept, counts = verify([claim(region_span(), excerpt="total: REAL (USD)")], store_with())
    assert kept == [] and counts.dropped == 1
    assert "a region claim quotes no text" in capsys.readouterr().err


def test_a_region_outside_the_bitmap_is_dropped(capsys):
    kept, counts = verify([claim(region_span(x=1300, w=200))], store_with())
    assert kept == [] and counts.dropped == 1
    assert "escapes the 1326x581 image" in capsys.readouterr().err


def test_a_region_whose_bytes_changed_is_dropped(capsys):
    span = region_span()
    span = span.model_copy(update={"content_hash": "0" * 64})
    kept, counts = verify([claim(span)], store_with())
    assert kept == [] and counts.dropped == 1
    assert "bytes changed" in capsys.readouterr().err


def test_a_verified_region_is_kept():
    span = region_span().model_copy(update={"content_hash": SpanStore([Root(id="r", path=DIAGRAM.parent)]).hash(DIAGRAM.name)})
    kept, counts = verify([claim(span)], store_with())
    assert len(kept) == 1 and counts.dropped == 0


def test_verification_carries_the_region_into_the_envelope():
    service = ContextService.__new__(ContextService)  # the verifier is pure: no graph, no model
    service.spans = store_with()
    verified, gaps = service._verify(
        [{"path": DIAGRAM.name, "start_line": 1, "end_line": 1, "hash": "", "region": [100, 50, 200, 40]}], 1
    )
    assert gaps == []
    assert verified[0]["region"] == [100, 50, 200, 40]
    assert verified[0]["lines"] == [1, 1]


def test_two_regions_on_one_image_are_two_citations():
    store = store_with()
    service = ContextService.__new__(ContextService)
    service.spans = store
    digest = store.hash(DIAGRAM.name)
    same = {"path": DIAGRAM.name, "start_line": 1, "end_line": 1, "hash": digest}
    verified, gaps = service._verify(
        [dict(same, region=[100, 50, 200, 40]), dict(same, region=[500, 50, 200, 40])], 5
    )
    assert gaps == []
    assert [v["region"] for v in verified] == [[100, 50, 200, 40], [500, 50, 200, 40]]


def test_a_malformed_region_is_a_gap_not_a_crash():
    service = ContextService.__new__(ContextService)
    service.spans = store_with()
    verified, gaps = service._verify([{"path": DIAGRAM.name, "region": [1, 2, 3]}], 1)
    assert verified == [] and "malformed region" in gaps[0]


def test_a_region_outside_the_bitmap_is_a_gap_on_the_query_path_too():
    """The gate and the answer path must agree: `_verify` checks bounds, not only the digest."""
    store = store_with()
    service = ContextService.__new__(ContextService)
    service.spans = store
    verified, gaps = service._verify(
        [{"path": DIAGRAM.name, "start_line": 1, "end_line": 1, "hash": "", "region": [1300, 0, 200, 20]}], 1
    )
    assert verified == []
    assert "escapes the 1326x581 image" in gaps[0]


def test_a_region_citation_resolves_to_pixels_not_text():
    """`/v1/span?region=` and MCP `resolve_span` share one implementation."""
    from toolcall import span

    class Backend:
        spans = store_with()

    result = span(Backend(), DIAGRAM.name, region="100,50,200,40")
    assert result["media_type"] == "image/png"
    assert result["bytes"] > 100
    import base64

    assert base64.b64decode(result["image_base64"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_region_outside_the_bitmap_is_a_bad_region_not_a_crop():
    from toolcall import span

    class Backend:
        spans = store_with()

    result = span(Backend(), DIAGRAM.name, region="1300,0,200,20")
    assert result["error"] == "bad_region"


def test_lines_or_region_is_a_caller_error_naming_both():
    from toolcall import span

    class Backend:
        spans = store_with()

    with pytest.raises(ValueError, match="region"):
        span(Backend(), DIAGRAM.name)
