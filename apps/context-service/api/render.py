# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Answer → plain text for a terminal or chat. VALID first, then what not to use."""

from models.answer import Answer, Statement


def _window(st: Statement) -> str:
    start = st.valid_from.isoformat() if st.valid_from else "?"
    end = st.valid_to.isoformat() if st.valid_to else "now"
    return f"{start} → {end}"


def _block(st: Statement) -> list[str]:
    lines = [
        f"- {st.text}",
        f"    status {st.status} · confidence {st.confidence:.2f} · {_window(st)}"
        f" · sources {', '.join(t.lower() for t in st.source_types)}",
        f"    why: {st.reason}",
    ]
    for c in st.citations:
        via = f" (via {c.via})" if c.via else ""
        lines.append(f"    cite: {c.path}:{c.lines[0]}-{c.lines[1]}{via}")
    for c in st.superseded_by:
        lines.append(f"    replaced by: {c.path}:{c.lines[0]}-{c.lines[1]}")
    return lines


def render_text(answer: Answer) -> str:
    out = [f"Q: {answer.question}  (as of {answer.as_of})", f"A: {answer.answer}", ""]
    out.append("VALID — current, evidence-backed, safe to use:")
    out += [line for st in answer.claims for line in _block(st)] or ["  (none)"]
    out += ["", "NOT VALID — stale, proposed, planned, disputed or too weak; not current:"]
    out += [line for st in answer.not_valid for line in _block(st)] or ["  (none)"]
    if answer.conflicts:
        out += ["", "CONFLICTS:"]
        out += [f"- {' <> '.join(c.statements)}: {c.reason}" for c in answer.conflicts]
    if answer.gaps:
        out += ["", "GAPS:"] + [f"- {g}" for g in answer.gaps]
    if answer.degraded:
        out += ["", f"degraded: {answer.degraded_reason}"]
    if answer.truncated:
        out += ["truncated: token budget reached"]
    return "\n".join(out)
