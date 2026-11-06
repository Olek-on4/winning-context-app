# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Header pass: a document's own declared status. One reader for every source type —
`Status: Accepted with review` (ADRs) and `Deferred · 2026-07-17` (issues) are the same
fact in two spellings. Unknown words are ignored, never guessed."""

import re

from models.ontology import DocStatus, Modality
from settings import Settings

_HEADER_LINES = 6
_STATUS_LINE = re.compile(
    r"^(?:Status:\s*)?(?P<word>[A-Za-z][A-Za-z ]*?)(?:\s*·\s*\d{4}-\d{2}-\d{2})?\s*$"
)


def declared_status(lines: list[str]) -> DocStatus | None:
    for line in lines[:_HEADER_LINES]:
        explicit = line.startswith("Status:")
        dated = "·" in line
        if not (explicit or dated):
            continue
        if (m := _STATUS_LINE.match(line.strip())) is None:
            continue
        try:
            return DocStatus(m.group("word").strip().lower())
        except ValueError:
            continue
    return None


def capped_modality(modality: Modality, status: DocStatus | None, cfg: Settings) -> Modality:
    """An unsettled document cannot decide: a DECISION in a proposed ADR is a proposal,
    in a deferred ticket a plan. Facts it reports and prohibitions it states stand."""
    if status is None or modality is not Modality.DECISION:
        return modality
    return cfg.doc_statuses[status].decision_becomes or modality
