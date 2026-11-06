# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
from datetime import date
from pathlib import Path

import pytest

from graph.resolve import resolve
from graph.scoring import corroborate, freshness
from models.claim import ClaimRecord, ResolvedClaim
from models.ontology import Polarity, SourceType, Status
from settings import Settings
from tests.conftest import TODAY


def _find(resolved: list[ResolvedClaim], path: str, polarity: Polarity | None = None,
          obj: str | None = None) -> ResolvedClaim:  # fmt: skip
    hits = [
        r for r in resolved
        if r.claim.evidence[0].path == path
        and (polarity is None or r.claim.polarity == polarity)
        and (obj is None or r.claim.object.key == obj)
    ]  # fmt: skip
    assert len(hits) == 1, [h.claim.id for h in hits]
    return hits[0]


def test_freshness_is_one_without_a_later_contradiction() -> None:
    cfg = Settings(repo_root=Path("."))
    assert freshness(date(2026, 1, 1), [], cfg) == 1.0
    assert freshness(date(2026, 1, 1), [date(2025, 12, 1)], cfg) == 1.0


def test_freshness_halves_per_half_life_and_stops_at_the_floor() -> None:
    cfg = Settings(repo_root=Path("."))
    assert freshness(date(2026, 1, 1), [date(2026, 5, 1)], cfg) == pytest.approx(0.5, abs=0.01)
    assert freshness(date(2026, 1, 1), [date(2026, 3, 2)], cfg) == pytest.approx(0.707, abs=0.01)
    assert freshness(date(2025, 1, 1), [date(2026, 6, 1)], cfg) == cfg.freshness_floor


def test_corroboration_combines_independent_sources() -> None:
    assert corroborate([0.76, 0.722]) == pytest.approx(0.9333, abs=1e-4)
    assert corroborate([]) == 0.0


def test_score_is_the_product_of_five_factors(records: list[ClaimRecord], cfg: Settings) -> None:
    wiki = _find(resolve(records, TODAY, cfg), "wiki/inventory-service.md", obj="redis")
    s = wiki.score
    assert (s.authority, s.time_confidence, s.extractor_confidence) == (0.45, 0.90, 0.8)
    assert s.settledness == 1.0
    newest_contradiction = date(2026, 6, 11)  # issues/INV-190.md, closed
    age = (newest_contradiction - date(2026, 2, 17)).days
    assert s.freshness == pytest.approx(0.5 ** (age / 120), abs=1e-3)
    assert s.score == pytest.approx(
        s.authority * s.time_confidence * s.extractor_confidence * s.settledness * s.freshness,
        abs=1e-3,
    )


def test_weak_late_contradiction_cannot_overrule_a_migration(
    records: list[ClaimRecord], cfg: Settings
) -> None:
    """supersede_ratio: a much weaker later claim leaves the strong one standing."""
    path = "apps/user-service/migrations/002-account-tiers.sql"
    migration = _find(resolve(records, TODAY, cfg), path, Polarity.NEGATES)
    wiki_like = migration.claim.model_copy(
        update={"id": "late-wiki", "polarity": Polarity.ASSERTS, "source_type": "WIKI",
                "observed_at": date(2026, 9, 1), "valid_from": date(2026, 9, 1), "confidence": 0.5}
    )  # fmt: skip
    out = resolve([migration.claim, wiki_like], TODAY, cfg)
    statuses = {r.claim.id: r.status for r in out}
    assert statuses[migration.claim.id] is Status.VALID
    assert statuses["late-wiki"] is Status.DISPUTED


def test_diagram_alone_is_not_enough(records: list[ClaimRecord], cfg: Settings) -> None:
    only_diagram = [
        r
        for r in records
        if r.evidence[0].path == "diagrams/architecture-september.png" and r.object.key == "sqlite"
    ]
    (r,) = resolve(only_diagram, TODAY, cfg)
    assert r.status is Status.DISPUTED
    assert "diagram-only" in r.reason


def test_point_in_time_sees_only_what_existed(records: list[ClaimRecord], cfg: Settings) -> None:
    march = resolve(records, date(2026, 3, 1), cfg)
    assert _find(march, "wiki/inventory-service.md", obj="redis").status is Status.VALID
    assert all(
        r.claim.observed_at is None or r.claim.observed_at <= date(2026, 3, 1) for r in march
    )


def test_resolution_is_deterministic(records: list[ClaimRecord], cfg: Settings) -> None:
    a = [r.model_dump_json() for r in resolve(records, TODAY, cfg)]
    b = [r.model_dump_json() for r in resolve(list(reversed(records)), TODAY, cfg)]
    assert a == b


def test_month_precision_successor_closes_at_month_end(
    records: list[ClaimRecord], cfg: Settings
) -> None:
    """docs/04 partial dates: a June release closes the old claim on June 30, and
    before June ends the old claim is disputed, not silently deprecated."""
    wiki = next(r for r in records if r.evidence[0].path == "wiki/inventory-service.md"
                and r.object.key == "redis")  # fmt: skip
    release = next(r for r in records if r.evidence[0].path == "releases/2026-06-v1.3.md"
                   and r.object.key == "redis")  # fmt: skip

    after = {r.claim.id: r for r in resolve([wiki, release], date(2026, 7, 1), cfg)}
    during = {r.claim.id: r for r in resolve([wiki, release], date(2026, 6, 10), cfg)}

    assert after[wiki.id].status is Status.DEPRECATED
    assert after[wiki.id].valid_to == date(2026, 6, 30)
    assert after[wiki.id].valid_to_precision == "month"
    assert during[wiki.id].status is Status.DISPUTED


def test_unsettled_document_scores_lower(records: list[ClaimRecord], cfg: Settings) -> None:
    out = resolve(records, TODAY, cfg)
    proposed = _find(out, "docs/adr/004-people-sso.md", obj="ADR-004")
    with_review = _find(out, "docs/adr/005-support-access.md")
    assert proposed.claim.declared_status == "proposed" and proposed.score.settledness == 0.60
    assert with_review.claim.declared_status == "accepted with review"
    assert with_review.score.settledness == 0.90


def test_rules_come_from_the_policy_table_not_the_code(
    records: list[ClaimRecord], cfg: Settings
) -> None:
    """Reuse across data types: flip one row, behaviour follows for that type."""
    port = [r for r in records if r.predicate == "LISTENS_ON"]
    assert {r.status for r in resolve(port, TODAY, cfg)} == {Status.VALID}

    sources = dict(cfg.sources)
    sources[SourceType.WIKI] = sources[SourceType.WIKI].model_copy(
        update={"needs_corroboration": True}
    )
    sources[SourceType.CONFIG] = sources[SourceType.CONFIG].model_copy(
        update={"needs_corroboration": True}
    )
    strict = cfg.model_copy(update={"sources": sources})
    assert {r.status for r in resolve(port, TODAY, strict)} == {Status.DISPUTED}
