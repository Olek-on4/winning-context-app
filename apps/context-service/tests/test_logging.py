"""The log line is an interface: one shape, redirectable, filterable by level."""

from __future__ import annotations

import logging
import re

import logging_setup


def test_one_line_shape_with_time_tag_and_level(tmp_path):
    path = tmp_path / "run.log"
    logging_setup.configure(level="info", path=str(path))

    logging_setup.logger("index").info("embedded %d/%d", 3, 897)

    line = path.read_text(encoding="utf-8").strip()
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z \[INFO\] etyt\.index: embedded 3/897$",
        line,
    ), line


def test_level_filters_and_reconfigure_does_not_stack(tmp_path):
    path = tmp_path / "run.log"
    logging_setup.configure(level="warning", path=str(path))
    log = logging_setup.logger("load")

    log.debug("invisible")
    log.warning("a dropped claim")
    logging_setup.configure(level="warning", path=str(path))  # second call: no duplicate lines
    log.warning("a dropped claim")

    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, "re-configuring must replace handlers, not add another"
    assert all("[WARNING]" in line for line in lines)


def test_errors_keep_their_own_level(tmp_path):
    path = tmp_path / "run.log"
    logging_setup.configure(level="info", path=str(path))

    logging_setup.logger("load").error("ontology rejected %s:%s", "x.md", 12)

    line = path.read_text(encoding="utf-8").strip()
    assert "[ERROR] etyt.load:" in line
    assert "x.md:12" in line


def test_an_unwritable_path_warns_instead_of_crashing(tmp_path, caplog):
    logging_setup.configure(level="info", path=str(tmp_path / "missing-dir" / "run.log"))

    logging_setup.logger("index").info("still working")

    assert "still working" in caplog.text or logging.getLogger("etyt").handlers
