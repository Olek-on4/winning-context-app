"""A corpus nobody wrote a pipeline for: extraction must be layout-blind.

The three files below use names and directories that appear nowhere in the
corpus, so passing here means the pipelines key off content, not off a known tree.
"""

from __future__ import annotations

import subprocess
from datetime import date
from pathlib import Path

import pytest

from ingest import registry
from sources import discover, root_id

FILES = {
    "schema/001-x.sql": "ALTER TABLE widget RENAME COLUMN old TO new;\n",
    "conf/ports.json": '{"widget-api": 7001}\n',
    "notes/decision.md": "# Decision\n\nStatus: Accepted\n",
}


def _corpus(base: Path) -> Path:
    for relative, text in FILES.items():
        target = base / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return base


def _git(base: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(base), *args], check=True, capture_output=True, text=True)


def test_unseen_layout_extracts_with_dates_and_root_prefixed_pointers(tmp_path):
    _corpus(tmp_path)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "corpus")

    [root] = discover([tmp_path])
    claims = registry.extract(root)

    assert root.id == root_id(tmp_path)
    assert {c.predicate for c in claims} == {"HAS_COLUMN", "LISTENS_ON", "HAS_STATUS"}
    assert all(c.observed_at is not None for c in claims)
    assert all(c.evidence[0].path.startswith(f"{root.id}/") for c in claims)
    assert {c.evidence[0].path for c in claims} == {f"{root.id}/{relative}" for relative in FILES}


def test_directory_without_git_still_dates_and_extracts(tmp_path):
    """Issue 84: a root outside git used to yield nothing at all, silently."""
    base = _corpus(tmp_path)
    if any((parent / ".git").exists() for parent in (base, *base.parents)):
        pytest.skip("temporary directory sits inside a git work tree")

    [root] = discover([base])
    claims = registry.extract(root)

    assert {c.predicate for c in claims} == {"HAS_COLUMN", "LISTENS_ON", "HAS_STATUS"}
    mtime = date.fromtimestamp((base / "conf/ports.json").stat().st_mtime)
    ports = next(c for c in claims if c.predicate == "LISTENS_ON")
    assert ports.observed_at == mtime  # no git, no Date: line — the file's own mtime dates it
    assert ports.excerpt == '{"widget-api": 7001}'  # and the gate gets something to verify


def test_reindex_drops_chunks_whose_file_vanished(tmp_path):
    """Issue 23: a deleted or renamed file must not stay retrievable forever."""
    from graph.chunks import index, sweep
    from sources import discover

    class Recorder:
        """Minimal driver stub: records the sweep statements, no Neo4j needed."""

        def __init__(self):
            self.calls = []

        def session(self):
            outer = self

            class Session:
                def run(self, query, **params):
                    outer.calls.append((query, params))

                    class Result:
                        counters = type("C", (), {"nodes_deleted": 0})()

                        def consume(self):
                            return self

                    return Result()

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            return Session()

    keep = tmp_path / "keep.md"
    keep.write_text("# kept\n\nbody\n", encoding="utf-8")
    gone = tmp_path / "gone.md"
    gone.write_text("# gone\n\nbody\n", encoding="utf-8")
    root = discover([tmp_path])[0]

    index(Recorder(), [root])          # both files indexed
    gone.unlink()
    driver = Recorder()
    index(driver, [root])              # second pass must name only the survivor

    sweeps = [params for query, params in driver.calls if "DETACH DELETE ch" in query]
    assert sweeps, "no sweep ran"
    assert sweeps[0]["prefix"] == f"{root.id}/"
    assert any(path.endswith("keep.md") for path in sweeps[0]["keep"])
    assert not any(path.endswith("gone.md") for path in sweeps[0]["keep"])
    assert sweep(driver, root, set()) == 0  # counters surface, nothing raised


def test_deploy_config_pipeline_reads_any_repo_layout(tmp_path):
    """Issue 4: compose, manifests and CODEOWNERS are facts, not Northstar specifics."""
    import subprocess

    from ingest.registry import extract
    from sources import discover

    (tmp_path / "compose.yaml").write_text(
        "services:\n  api:\n    image: x\n    depends_on:\n      - db\n  db:\n    image: y\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text('{"dependencies": {"left-pad": "^1.0.0"}}', encoding="utf-8")
    (tmp_path / ".github").mkdir()
    (tmp_path / ".github" / "CODEOWNERS").write_text("/api/ @team/api\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"],
        cwd=tmp_path, check=True,
    )

    claims = extract(discover([tmp_path])[0])
    triples = {(c.subject.key, c.predicate, c.object) for c in claims}

    assert ("api", "DEPENDS_ON", "db") in triples
    assert any(pred == "DEPENDS_ON" and obj == "left-pad" for _, pred, obj in triples)
    assert any(pred == "OWNS" for _, pred, _ in triples)
    assert all(c.observed_at is not None for c in claims)


def test_source_type_parsing_rejects_unknown_and_keeps_colons_in_paths():
    """Issue 69: `--type adr` used to vanish; an unknown type is now an error naming the valid ones."""
    from sources import split_typed

    assert split_typed("adr:/tmp/x") == ("adr", Path("/tmp/x"))
    assert split_typed("/tmp/a:b") == (None, Path("/tmp/a:b"))
    assert split_typed("../corpus") == (None, Path("../corpus"))
    with pytest.raises(ValueError) as error:
        split_typed("nonsense:/tmp/x")
    assert "adr" in str(error.value) and "sql" in str(error.value)


def test_each_declared_type_probes_its_own_shape(tmp_path):
    from sources import probe

    trees = {
        "adr": ("docs/001-x.md", "# Decision\n\nStatus: Accepted\n"),
        "api-specs": ("api/openapi.json", '{"openapi": "3.1.0", "paths": {"/v1/x": {}}}\n'),
        "sql": ("db/001.sql", "CREATE TABLE widget (id int);\n"),
        "config": ("conf/ports.yaml", "widget-api: 7001\n"),
        "docs": ("docs/guide.md", "# Guide\n"),
        "code": ("src/main.py", "print('hi')\n"),
    }
    for kind, (relative, text) in trees.items():
        base = tmp_path / kind
        target = base / relative
        target.parent.mkdir(parents=True)
        target.write_text(text, encoding="utf-8")
        [root] = discover([base])

        ok, reason = probe(kind, root)
        assert ok, f"{kind} did not probe its own tree: {reason}"


def test_probe_explains_a_mismatch_with_what_is_actually_there(tmp_path):
    """Issue 69: skipping a root is only auditable if the reason names the real contents."""
    from sources import probe

    base = tmp_path / "schema"
    base.mkdir()
    (base / "001.sql").write_text("CREATE TABLE widget (id int);\n", encoding="utf-8")
    [root] = discover([base])

    ok, reason = probe("adr", root)
    assert not ok
    assert "no markdown files" in reason and ".sql" in reason


def test_typed_sources_skip_a_mismatch_but_extract_the_match(tmp_path, monkeypatch, capsys):
    """The CLI path: one matching adr root, one root that only holds SQL (issue 69)."""
    import cli
    from sources import split_typed

    matching = tmp_path / "decisions"
    matching.mkdir()
    (matching / "001-choice.md").write_text("# Choose SQLite\n\nStatus: Accepted\n", encoding="utf-8")
    mismatched = tmp_path / "schema"
    mismatched.mkdir()
    (mismatched / "001.sql").write_text("CREATE TABLE widget (id int);\n", encoding="utf-8")

    roots = cli._sources([f"adr:{matching}", f"adr:{mismatched}"])

    err = capsys.readouterr().err
    assert [root.id for root in roots] == [split_typed(f"adr:{matching}")[1].name]
    assert "claimed adr" in err and str(mismatched) in err and "no markdown files" in err


def test_no_surviving_typed_root_is_fatal(tmp_path):
    import cli

    base = tmp_path / "schema"
    base.mkdir()
    (base / "001.sql").write_text("CREATE TABLE widget (id int);\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        cli._sources([f"adr:{base}"])


def test_extract_command_writes_claims_and_reports_the_skip(tmp_path, monkeypatch, capsys):
    """Acceptance for issue 69: probe line on stderr, skip, exit 0, JSON on stdout."""
    import json

    import cli

    matching = tmp_path / "decisions"
    matching.mkdir()
    (matching / "001-choice.md").write_text("# Choose\n\nDate: 2026-03-01\nStatus: Accepted\n", encoding="utf-8")
    mismatched = tmp_path / "schema"
    mismatched.mkdir()
    (mismatched / "001.sql").write_text("CREATE TABLE widget (id int);\n", encoding="utf-8")
    out = tmp_path / "claims.jsonl"
    monkeypatch.setenv("EXTRACTED_PATH", str(out))

    cli.extract_claims(f"adr:{matching}", f"adr:{mismatched}")

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["claims"] == 2  # Status: and Date: from the one surviving root
    assert "claimed adr" in captured.err and "skipped" in captured.err
    assert out.read_text().count("\n") == 2


def test_unknown_text_extension_is_included_and_binary_is_reported(tmp_path, capsys):
    """Issue 84: `.properties`, `.html`, `.env.example` and extensionless text are facts."""
    from sources import iter_files

    (tmp_path / "app.properties").write_text("stock.cache=redis\n", encoding="utf-8")
    (tmp_path / "index.html").write_text("<html><body>console</body></html>\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("CACHE_URL=redis://localhost\n", encoding="utf-8")
    (tmp_path / "Dockerfile.web").write_text("FROM python:3.12\n", encoding="utf-8")
    (tmp_path / "settings").write_text("theme=dark\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02binary\x00")

    [root] = discover([tmp_path])
    found = {relative.as_posix() for relative, _ in iter_files(root)}

    assert found == {"app.properties", "index.html", ".env.example", "Dockerfile.web", "settings"}
    assert "skip" in capsys.readouterr().err


def test_a_declared_type_reaches_the_claims_it_types(tmp_path):
    """`--source adr:` types what path inference would otherwise call narrative prose."""
    from models.claim import SourceType
    from sources import Root

    base = tmp_path / "decisions"
    base.mkdir()
    (base / "001-choice.md").write_text("# Choose SQLite\n\nDate: 2026-03-01\nStatus: Accepted\n", encoding="utf-8")

    claims = registry.extract(Root("decisions", base, kind="adr"))

    assert {claim.source_type for claim in claims} == {SourceType.ADR}
