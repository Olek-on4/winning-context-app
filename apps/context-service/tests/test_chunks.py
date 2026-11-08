"""Chunk ids must be unique per root, or the loader's MERGE overwrites real text.

A long body under one heading flushes repeatedly; per-body indices restarted at zero and
collapsed the windows onto one id (1119 windows -> 685 ids on the corpus).
"""

from __future__ import annotations

from pathlib import Path

from graph import chunks as chunk_index
from graph.chunks import EMBED_DIM, TARGET_CHARS, chunks_for, index
from retrieval import hybrid
from sources import Root


class _Result:
    class counters:
        nodes_deleted = 0

    def consume(self):
        return self


class CaptureDriver:
    """Records the batches the loader writes; a round trip needs no Neo4j."""

    def __init__(self) -> None:
        self.batches: list[list[dict]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def session(self):
        return self

    def run(self, query, **params):
        if "UNWIND $chunks" in query:
            self.batches.append(params["chunks"])
        return _Result()

    @property
    def stored(self) -> list[dict]:
        return [props for batch in self.batches for props in batch]


def test_repeated_flushes_under_one_heading_keep_distinct_ids(tmp_path):
    body = "".join(f"line {index:05d} of a long table under one heading\n" for index in range(600))
    assert len(body) > TARGET_CHARS * 4, "fixture must force at least two flushes"
    (tmp_path / "notes.md").write_text(f"# One heading\n\n{body}", encoding="utf-8")

    chunks = chunks_for(Root("corpus", tmp_path))

    assert len(chunks) > 1
    assert len({chunk["id"] for chunk in chunks}) == len(chunks)
    assert "".join(chunk["text"].replace("One heading\n", "") for chunk in chunks).count("line 00599") == 1


def test_a_chunk_round_trips_its_line_range(tmp_path):
    """#83: nothing wrote `start_line`/`end_line`, so every vector candidate came back
    with `lines: []` and could not be resolved back to bytes."""
    (tmp_path / "notes.md").write_text(
        "# Alpha\nalpha one\nalpha two\n\n# Beta\nbeta one\nbeta two\n", encoding="utf-8"
    )
    chunks = chunks_for(Root("corpus", tmp_path))
    driver = CaptureDriver()
    chunk_index._flush(driver, chunks)

    file_lines = (tmp_path / "notes.md").read_text(encoding="utf-8").splitlines()
    assert len(driver.stored) == len(chunks)
    for props in driver.stored:
        rendered = hybrid._chunk(props, 1.0, "bm25", "")
        assert rendered["lines"] == [props["start_line"], props["end_line"]]
        assert rendered["lines"], "a chunk without a range cannot be cited"
        assert rendered["path"] == props["path"] == "corpus/notes.md"
        assert props["root"] == "corpus"
        cited = file_lines[props["start_line"] - 1 : props["end_line"]]
        assert props["text"].splitlines()[-1].strip() in [line.strip() for line in cited]


def test_windows_point_at_the_lines_they_carry(tmp_path):
    body = "".join(f"row {index:04d}\n" for index in range(400))
    (tmp_path / "table.md").write_text(f"# Table\n\n{body}", encoding="utf-8")

    chunks = chunks_for(Root("corpus", tmp_path))
    file_lines = (tmp_path / "table.md").read_text(encoding="utf-8").splitlines()

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk["start_line"] <= chunk["end_line"], chunk
        assert chunk["end_line"] <= len(file_lines), chunk
        # The window ends inside its last cited line: a cut mid-line still points there.
        assert chunk["text"].splitlines()[-1].strip() in file_lines[chunk["end_line"] - 1]


def test_upsert_writes_the_pointer_properties():
    """The properties hybrid reads must be the ones the MERGE actually sets."""
    for prop in ("start_line", "end_line", "root", "path"):
        assert f"ch.{prop} = c.{prop}" in chunk_index.UPSERT, prop


def test_index_refuses_a_vector_of_the_wrong_width(tmp_path, capsys):
    """#79: `_embed` raised on a width mismatch and the CLI swallowed it into a
    lexical-only index that still reported `embedded: true`."""
    (tmp_path / "notes.md").write_text("# Alpha\nalpha\n", encoding="utf-8")
    driver = CaptureDriver()

    outcome = index(driver, [Root("corpus", tmp_path)], embed=lambda text: [0.0] * 1024)

    assert outcome.embedded is False
    assert outcome.as_dict()["embedded"] is False
    assert outcome.as_dict()["reason"]
    warning = capsys.readouterr().err
    assert "1024" in warning and str(EMBED_DIM) in warning, warning
    assert all("embedding" not in props for props in driver.stored)


def test_index_reports_vectors_it_wrote(tmp_path):
    (tmp_path / "notes.md").write_text("# Alpha\nalpha\n", encoding="utf-8")

    outcome = index(
        CaptureDriver(), [Root("corpus", tmp_path)], embed=lambda text: [0.0] * EMBED_DIM
    )

    assert outcome.embedded is True
    assert "reason" not in outcome.as_dict()
    assert int(outcome) >= 1


def test_index_without_an_embedder_says_why(tmp_path):
    (tmp_path / "notes.md").write_text("# Alpha\nalpha\n", encoding="utf-8")

    outcome = index(CaptureDriver(), [Root("corpus", tmp_path)])

    assert outcome.embedded is False
    assert "no embedding model" in outcome.as_dict()["reason"]


def test_the_index_width_is_the_one_the_schema_declares():
    """One constant: schema.cypher and hybrid._embed cannot drift from EMBED_DIM."""
    schema = Path(chunk_index.__file__).with_name("schema.cypher").read_text(encoding="utf-8")

    assert f"`vector.dimensions`: {EMBED_DIM}" in schema
