"""The opt-in gate: a capability the operator must approve, and every way to answer."""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from ingest import registry
from ingest.optin import OptIn, agree
from models.claim import ClaimRecord, EntityRef, Polarity, SourceType, Span
from sources import Root

GATED = OptIn(
    name="test-gated",
    licence="GPL-2.0-or-later (test)",
    why="buys a claim, costs nothing",
    modules=("json",),  # any importable module: this test is about consent, not about OCR
)

ABSENT = OptIn(
    name="test-absent",
    licence="GPL-3.0 (test)",
    why="never installed here",
    modules=("definitely_not_an_installed_module_etyt",),
)


def test_declining_is_the_same_output_as_not_having_the_module():
    """The licence promise: the default result does not depend on the gated code."""
    assert agree(GATED, files=3, ask=lambda _: "") == agree(GATED, files=3, ask=lambda _: "" )
    yes = agree(GATED, files=3, ask=lambda _: "y")
    no = agree(GATED, files=3, rejected=frozenset({GATED.name}))
    assert yes.allowed and not no.allowed


def test_explicit_refusal_beats_acceptance():
    decision = agree(GATED, files=1, accepted=frozenset({GATED.name}), rejected=frozenset({GATED.name}))
    assert decision.allowed is False
    assert decision.reason == "--decline-opt-in"


def test_absent_module_is_never_asked_about():
    calls: list[str] = []
    decision = agree(ABSENT, files=5, ask=lambda q: calls.append(q) or "y", stream=io.StringIO())
    assert decision.allowed is False
    assert "not installed" in decision.reason
    assert calls == [], "a missing dependency is a fact, not a question"


def test_non_interactive_run_skips_and_names_the_flag():
    decision = agree(GATED, files=2, ask=None, stream=io.StringIO())
    assert decision.allowed is False
    assert GATED.name in decision.reason and "--accept-opt-in" in decision.reason


def test_the_prompt_states_licence_file_count_and_cost():
    out = io.StringIO()
    agree(GATED, files=7, ask=lambda _: "y", stream=out)
    shown = out.getvalue()
    assert "7 file(s)" in shown
    assert GATED.licence in shown
    assert GATED.why in shown


@pytest.mark.parametrize("answer", ["", "n", "no", "N", "maybe", "\\n"])
def test_only_y_and_yes_mean_yes(answer):
    assert agree(GATED, files=1, ask=lambda _: answer, stream=io.StringIO()).allowed is False


class GatedPipeline:
    """A pipeline that claims every `.gated` file; the gate decides whether it runs."""

    name = "test.gated"
    opt_in = GATED

    def matches(self, path: Path) -> bool:
        return path.suffix == ".gated"

    def extract(self, root: Root, path: Path, digest: str):
        yield ClaimRecord(
            subject=EntityRef(kind="File", key=path.stem),
            predicate="HAS",
            object="gate",
            polarity=Polarity.ASSERTS,
            observed_at=None,  # skipped by the walker's undated gap, so count calls instead
            source_type=SourceType.CODE,
            extractor=self.name,
            evidence=[Span(path=root.pointer(path.relative_to(root.path)), start_line=1, end_line=1, content_hash=digest)],
        )


def test_walker_asks_once_and_skips_all_files_when_declined(tmp_path: Path, monkeypatch):
    (tmp_path / "a.gated").write_text("x", encoding="utf-8")
    (tmp_path / "b.gated").write_text("y", encoding="utf-8")
    pipeline = GatedPipeline()
    monkeypatch.setattr(registry, "PIPELINES", [pipeline])
    prompts: list[str] = []
    out = io.StringIO()

    claims = registry.extract(
        Root(id="t", path=tmp_path, kind=None), ask=lambda q: prompts.append(q) or "n", stream=out
    )

    assert claims == []
    assert len(prompts) == 1, "consent is asked once, not once per file"
    assert "2 file(s)" in out.getvalue()
    assert "skipped 2 file(s) for test.gated" in out.getvalue()


def test_walking_a_gated_pipeline_runs_when_accepted(tmp_path: Path):
    (tmp_path / "a.gated").write_text("x", encoding="utf-8")
    pipeline = GatedPipeline()
    original = registry.PIPELINES
    registry.PIPELINES = [pipeline]
    try:
        ran: list[Path] = []
        pipeline.extract = lambda root, path, digest: (ran.append(path), iter(()))[1]
        registry.extract(Root(id="t", path=tmp_path, kind=None), accepted=frozenset({GATED.name}))
    finally:
        registry.PIPELINES = original
    assert ran == [tmp_path / "a.gated"]


class ImagePipeline:
    """Stands in for the real image extractor: claims .png, needs an opt-in dependency."""

    name = "test.image"
    opt_in = GATED

    def matches(self, path: Path) -> bool:
        return path.suffix == ".png"

    def extract(self, root: Root, path: Path, digest: str):
        yield ClaimRecord(
            subject=EntityRef(kind="File", key=path.stem),
            predicate="HAS",
            object="diagram",
            polarity=Polarity.ASSERTS,
            observed_at=None,
            source_type=SourceType.CODE,
            extractor=self.name,
            evidence=[Span(path=root.pointer(path), start_line=1, end_line=1, content_hash=digest)],
        )


def test_a_binary_file_reaches_the_gate_instead_of_being_refused_as_non_text(tmp_path: Path):
    """The defect this pins: the walker refused PNGs before routing, so the gate saw zero."""
    (tmp_path / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    original = registry.PIPELINES
    registry.PIPELINES = [ImagePipeline()]
    try:
        prompts: list[str] = []
        out = io.StringIO()
        registry.extract(Root(id="t", path=tmp_path, kind=None), ask=lambda q: prompts.append(q) or "n", stream=out)
    finally:
        registry.PIPELINES = original
    assert len(prompts) == 1, "the image found the prompt"
    assert "1 file(s)" in out.getvalue()


def test_the_same_binary_is_refused_when_no_gated_pipeline_claims_it(tmp_path: Path, capsys):
    (tmp_path / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    assert list(__import__("sources").iter_files(Root(id="t", path=tmp_path, kind=None))) == []
    assert "no UTF-8 text" in capsys.readouterr().err


def test_env_var_is_the_unattended_form(monkeypatch):
    import cli

    monkeypatch.setenv("ETYT_ACCEPT_OPT_IN", "diagram-ocr, other")
    monkeypatch.setenv("ETYT_DECLINE_OPT_IN", "")
    assert cli._opt_in_env("ETYT_ACCEPT_OPT_IN") == frozenset({"diagram-ocr", "other"})
    assert cli._opt_in_env("ETYT_DECLINE_OPT_IN") == frozenset()


def test_flags_parse_both_forms_and_leave_the_rest(capsys):
    import cli

    rest, accepted, rejected = cli._opt_in_flags(
        ["--accept-opt-in", "a", "--accept-opt-in=b", "--decline-opt-in=c", "--source", "x"]
    )
    assert rest == ["--source", "x"]
    assert accepted == ["a", "b"]
    assert rejected == ["c"]


def test_the_consent_decision_is_recorded_for_audit(tmp_path: Path):
    (tmp_path / "a.gated").write_text("x", encoding="utf-8")
    original = registry.PIPELINES
    registry.PIPELINES = [GatedPipeline()]
    record: dict[str, str] = {}
    try:
        registry.extract(
            Root(id="t", path=tmp_path, kind=None), ask=lambda _: "n", stream=io.StringIO(), record=record
        )
    finally:
        registry.PIPELINES = original
    assert record == {"test.gated": "declined (answered 'n')"}


def test_human_assist_is_refused_above_the_ceiling(monkeypatch):
    import settings
    from ingest.optin import human_assist_allowed

    monkeypatch.setattr(settings, "HUMAN_ASSIST_MAX_FILES", 20)
    assert human_assist_allowed(20)[0] is True
    allowed, reason = human_assist_allowed(21)
    assert allowed is False
    assert "21 files exceeds the 20-file" in reason
    assert "automatic route" in reason
