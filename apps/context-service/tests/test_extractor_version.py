"""A pipeline's version is its identity for invalidation: bump it and the old claims go.

Nothing set `extractor_version` before this: every one of the 284 extracted claims said
`"1"`, so an extractor could change its mind and the graph would hold both opinions.
"""

from __future__ import annotations

from graph.loader import DELETE_VERSION
from ingest import registry


def test_every_pipeline_declares_a_version():
    for pipeline in registry.PIPELINES:
        assert getattr(pipeline, "version", ""), f"{pipeline.name} does not version its output"


def test_claims_carry_the_pipeline_version(tmp_path, monkeypatch):
    sql = tmp_path / "migrations"
    sql.mkdir()
    (sql / "001.sql").write_text("ALTER TABLE orders ADD COLUMN total_minor INTEGER;\n", encoding="utf-8")
    root = __import__("sources").Root(id="t", path=tmp_path, kind=None)
    claims = registry.extract(root)
    assert claims, "the fixture must produce a claim for this test to mean anything"
    for claim in claims:
        source = next(p for p in registry.PIPELINES if p.name == claim.extractor)
        assert claim.extractor_version == source.version


def test_the_delete_is_version_scoped_to_one_extractor():
    """A version bump must not leave the old rows beside the new ones (ADR-0012)."""
    assert "{extractor: $extractor}" in DELETE_VERSION
    assert "cl.extractor_version <> $version" in DELETE_VERSION
    assert "DETACH DELETE cl" in DELETE_VERSION
