# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
import pytest

from models.answer import EvidenceFilter, TimeFilter
from models.claim import ClaimRecord
from models.ontology import FilterCode, SourceType, Status, Verdict
from service import SpanDrift, query, resolve_span
from settings import Settings
from tests.conftest import TODAY

QUESTION = "does inventory still use redis?"


def test_low_confidence_valid_claim_is_filtered_out(
    cfg: Settings, records: list[ClaimRecord]
) -> None:
    a = query(QUESTION, cfg, TimeFilter(as_of=TODAY), EvidenceFilter(min_confidence=0.97))
    weak = next(s for s in a.not_valid if s.text == "inventory-service NOT READS_FROM redis")
    assert weak.status is Status.VALID
    assert weak.verdict is Verdict.NOT_VALID
    assert weak.filtered_by is FilterCode.LOW_CONFIDENCE
    assert weak.reason.startswith("LOW_CONFIDENCE")


def test_valid_only_omits_everything_else(cfg: Settings, records: list[ClaimRecord]) -> None:
    a = query(QUESTION, cfg, TimeFilter(as_of=TODAY, status_in=[Status.VALID]), EvidenceFilter())
    assert {s.status for s in a.claims + a.not_valid} == {Status.VALID}
    assert all(s.filtered_by is FilterCode.LOW_CONFIDENCE for s in a.not_valid)


def test_budget_trims_not_valid_detail_before_valid_claims(
    cfg: Settings, records: list[ClaimRecord]
) -> None:
    tight = cfg.model_copy(update={"token_budget": 500})
    a = query(QUESTION, tight, TimeFilter(as_of=TODAY), EvidenceFilter())
    assert a.truncated
    assert a.claims, "valid claims are the last thing the budget removes"
    assert all(len(s.citations) <= 1 for s in a.not_valid)


def test_unrelated_question_reports_a_gap(cfg: Settings, records: list[ClaimRecord]) -> None:
    a = query("kubernetes helm chart values", cfg, TimeFilter(as_of=TODAY), EvidenceFilter())
    assert a.claims == [] and a.not_valid == []
    assert a.gaps == ["No claim in the index matches the question."]


def test_citation_resolves_to_untrusted_text_and_refuses_drift(
    cfg: Settings, records: list[ClaimRecord]
) -> None:
    a = query(QUESTION, cfg, TimeFilter(as_of=TODAY), EvidenceFilter())
    c = a.claims[0].citations[0]

    text = resolve_span(c.path, c.lines[0], c.lines[1], c.hash, cfg)

    assert text.startswith(f'<untrusted_source path="{c.path}"')
    assert text.count("</untrusted_source>") == 1
    with pytest.raises(SpanDrift):
        resolve_span(c.path, c.lines[0], c.lines[1], "0" * 64, cfg)
    with pytest.raises(SpanDrift):
        resolve_span("vendor/att-hackathon-task/../../AGENTS.md", 1, 1, c.hash, cfg)


def test_source_type_filter_shows_what_the_wiki_says_judged_against_everything(
    cfg: Settings, records: list[ClaimRecord]
) -> None:
    only_wiki = EvidenceFilter(source_types=[SourceType.WIKI])
    a = query(QUESTION, cfg, TimeFilter(as_of=TODAY), only_wiki)
    shown = a.claims + a.not_valid
    assert shown and all(SourceType.WIKI in s.source_types for s in shown)
    assert all(c.path.split("/")[2] == "wiki" for s in shown for c in s.citations)
    stale = next(s for s in a.not_valid if s.text == "inventory-service READS_FROM redis")
    assert stale.status is Status.DEPRECATED


def test_min_source_types_withholds_single_source_facts(
    cfg: Settings, records: list[ClaimRecord]
) -> None:
    strict = EvidenceFilter(min_source_types=2)
    a = query("which port does inventory listen on?", cfg, TimeFilter(as_of=TODAY), strict)
    port = next(s for s in a.claims if s.text == "inventory-service LISTENS_ON 5005")
    assert set(port.source_types) == {SourceType.CONFIG, SourceType.WIKI}

    b = query("operations console calls inventory", cfg, TimeFilter(as_of=TODAY), strict)
    single = next(s for s in b.not_valid if s.text == "operations-console CALLS inventory-service")
    assert single.status is Status.VALID
    assert single.filtered_by is FilterCode.SINGLE_SOURCE
