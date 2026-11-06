# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Deterministic date extraction — signals 1–3 and 6 of docs/04-temporal-model.md.
No model: a regex that reads `Date: 2026-06-04` beats any model and is free."""

import re
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from models.ontology import Precision, TimeSignal

_HEADER_LINES = 6
_EXPLICIT = re.compile(r"^Date: (\d{4}-\d{2}-\d{2})\s*$")
_FILENAME_DAY = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
_FILENAME_MONTH = re.compile(r"^(\d{4}-\d{2})-")
_ISO_DAY = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_MONTHS: list[str] = [
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
]  # fmt: skip
_TITLE_MONTH = re.compile(r"\b(" + "|".join(_MONTHS) + r") (\d{4})\b", re.IGNORECASE)


@dataclass(frozen=True)
class Dated:
    on: date
    precision: Precision
    signal: TimeSignal


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _month(text: str) -> date:
    return date.fromisoformat(f"{text}-01")


def date_from_content(path: str, lines: list[str]) -> Dated | None:
    """Highest-trust signal first. Month precision is normalised to the 1st."""
    header = lines[:_HEADER_LINES]
    for line in header:
        if m := _EXPLICIT.match(line):
            return Dated(_day(m.group(1)), Precision.DAY, TimeSignal.EXPLICIT_FIELD)

    name = PurePosixPath(path).name
    if m := _FILENAME_DAY.match(name):
        return Dated(_day(m.group(1)), Precision.DAY, TimeSignal.FILENAME)
    if m := _FILENAME_MONTH.match(name):
        return Dated(_month(m.group(1)), Precision.MONTH, TimeSignal.FILENAME)

    if path.endswith(".png"):
        for line in header:
            if m := _TITLE_MONTH.search(line):
                month = _MONTHS.index(m.group(1).lower()) + 1
                on = date(int(m.group(2)), month, 1)
                return Dated(on, Precision.MONTH, TimeSignal.DIAGRAM_TITLE)
        return None

    if path.endswith(".md"):
        for line in header:
            if m := _ISO_DAY.search(line):
                return Dated(_day(m.group(1)), Precision.DAY, TimeSignal.BYLINE)
    return None


def date_from_git(corpus_root: Path, path: str) -> Dated | None:
    """Last commit touching the file. Weak: file mtime is not fact validity."""
    out = subprocess.run(
        ["git", "-C", str(corpus_root), "log", "-1", "--format=%cs", "--", path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return Dated(_day(out), Precision.DAY, TimeSignal.GIT) if out else None
