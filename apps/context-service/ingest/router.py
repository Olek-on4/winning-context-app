# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Path → SourceType. Path first, because in this corpus the path is semantics:
`api-specs/history/` and `archive/` say "superseded" before any byte is read."""

from pathlib import PurePosixPath

from models.ontology import SourceType

_CONFIG_NAMES = {
    "package.json",
    "compose.yaml",
    "compose.yml",
    "requirements.txt",
    "pnpm-workspace.yaml",
    "turbo.json",
    "CODEOWNERS",
}
_CODE_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".py", ".java", ".graphql"}


def source_type(path: str) -> SourceType:
    p = PurePosixPath(path)
    parts = p.parts
    top = parts[0] if parts else ""

    if path.startswith("api-specs/history/") or top == "archive":
        return SourceType.HISTORICAL
    if "migrations" in parts and p.suffix == ".sql":
        return SourceType.MIGRATION
    if p.name in _CONFIG_NAMES or p.name.startswith("Dockerfile") or top == "config":
        return SourceType.CONFIG
    if top == "api-specs":
        return SourceType.API_SPEC
    if path.startswith("docs/adr/"):
        return SourceType.ADR
    if top == "releases":
        return SourceType.RELEASE
    if top in {"issues", "incidents"}:
        return SourceType.ISSUE
    if top == "meeting-notes":
        return SourceType.MEETING
    if top == "wiki":
        return SourceType.WIKI
    if top == "diagrams" and p.suffix == ".png":
        return SourceType.DIAGRAM
    if top == "docs" or (top in {"apps", "packages"} and p.suffix == ".md"):
        return SourceType.DESIGN_DOC
    if top in {"apps", "packages"} and p.suffix in _CODE_SUFFIXES:
        return SourceType.CODE
    return SourceType.OTHER
