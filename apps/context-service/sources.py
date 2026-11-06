"""Source roots: any directory can be plugged in, and every pointer carries its root.

A pointer is `"<root_id>/<relative/path>"`, so two corpora with the same file name never
collide and resolution never has to guess which tree a line came from. Readers stream
lines; nothing here loads a file into memory whole.
"""

from __future__ import annotations

import hashlib
import itertools
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

MAX_LINE_BYTES = 1 << 20  # a "line" longer than this is a binary blob; refuse it
_TEXT_SUFFIXES = {".md", ".txt", ".sql", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".ts", ".tsx",
                  ".js", ".mjs", ".py", ".java", ".graphql", ".csv"}
_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build", ".next"}


@dataclass(frozen=True)
class Root:
    id: str
    path: Path

    def pointer(self, relative: Path) -> str:
        return f"{self.id}/{relative.as_posix()}"


def root_id(path: Path) -> str:
    """Stable, readable, and safe in a pointer: the directory name, slugged."""
    return re.sub(r"[^a-z0-9_.-]+", "-", path.name.lower()).strip("-") or "root"


def discover(paths: Iterable[Path]) -> list[Root]:
    roots, seen, paths_seen = [], set(), set()
    for path in paths:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir() or resolved in paths_seen:  # the same tree twice is one root
            continue
        paths_seen.add(resolved)
        identifier = root_id(resolved)
        while identifier in seen:
            identifier = f"{identifier}-{len(seen)}"
        seen.add(identifier)
        roots.append(Root(identifier, resolved))
    return roots


def iter_files(root: Root) -> Iterator[tuple[Path, str]]:
    """Yield (relative path, streaming sha256). Sorted for determinism; no file is read whole."""
    for path in sorted(root.path.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if _SKIP_DIRS & set(path.relative_to(root.path).parts):
            continue
        yield path.relative_to(root.path), hash_file(path)


def hash_file(path: Path, chunk: int = 1 << 16) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def read_lines(path: Path, start: int, end: int) -> bytes:
    """Lines [start, end], 1-indexed inclusive, streamed — never the whole file."""
    if start < 1 or end < start:
        raise ValueError("start must be >= 1 and end must be >= start")
    out: list[bytes] = []
    with path.open("rb") as handle:
        for line in itertools.islice(handle, start - 1, end):
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("line too long to be text")
            out.append(line)
    if not out:
        raise ValueError(f"range {start}-{end} is past the end of {path.name}")
    return b"".join(out)


class SpanStore:
    """Turns a stored pointer back into bytes, and refuses to leave any registered root."""

    def __init__(self, roots: Iterable[Root], fallback: Path | None = None) -> None:
        self._roots = {r.id: r.path.resolve() for r in roots}
        self._hashes: dict[str, str] = {}
        if fallback is not None:
            self._roots.setdefault("", Path(fallback).resolve())

    def _base(self, pointer: str) -> tuple[Path, str]:
        """`<root>/<rel>` when the root is known; a bare path when only one tree exists."""
        identifier, _, relative = pointer.partition("/")
        if identifier in self._roots:
            return self._roots[identifier], relative
        if len(self._roots) == 1:
            return next(iter(self._roots.values())), pointer
        raise FileNotFoundError(pointer)

    def resolve(self, pointer: str) -> Path:
        base, relative = self._base(pointer)
        target = (base / relative).resolve(strict=True)
        if not target.is_relative_to(base) or not target.is_file():
            raise PermissionError(pointer)
        return target

    def hash(self, pointer: str) -> str:
        """Streamed digest, memoised as a 32-char string — never the file itself."""
        if pointer not in self._hashes:
            if len(self._hashes) > 512:
                self._hashes.clear()
            self._hashes[pointer] = hash_file(self.resolve(pointer))
        return self._hashes[pointer]

    def read(self, pointer: str, start: int, end: int) -> bytes:
        return read_lines(self.resolve(pointer), start, end)
