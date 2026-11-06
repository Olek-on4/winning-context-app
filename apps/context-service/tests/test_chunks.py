"""Chunk ids must be unique per root, or the loader's MERGE overwrites real text.

A long body under one heading flushes repeatedly; per-body indices restarted at zero and
collapsed the windows onto one id (1119 windows -> 685 ids on the corpus).
"""

from __future__ import annotations

from graph.chunks import TARGET_CHARS, chunks_for
from sources import Root


def test_repeated_flushes_under_one_heading_keep_distinct_ids(tmp_path):
    body = "".join(f"line {index:05d} of a long table under one heading\n" for index in range(600))
    assert len(body) > TARGET_CHARS * 4, "fixture must force at least two flushes"
    (tmp_path / "notes.md").write_text(f"# One heading\n\n{body}", encoding="utf-8")

    chunks = chunks_for(Root("corpus", tmp_path))

    assert len(chunks) > 1
    assert len({chunk["id"] for chunk in chunks}) == len(chunks)
    assert "".join(chunk["text"].replace("One heading\n", "") for chunk in chunks).count("line 00599") == 1
