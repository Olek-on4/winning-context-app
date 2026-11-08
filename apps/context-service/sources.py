"""Source roots: any directory can be plugged in, and every pointer carries its root.

A pointer is `"<root_id>/<relative/path>"`, so two corpora with the same file name never
collide and resolution never has to guess which tree a line came from. Readers stream
lines; nothing here loads a file into memory whole.

A root may also be *declared*: `--source adr:/path` says what the operator believes the
tree is, and `probe` checks that belief against the files before anything is extracted
(issue 69). Probing is pure filesystem work, so it is testable without a graph.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from models.claim import SourceType

MAX_LINE_BYTES = 1 << 20  # a "line" longer than this is a binary blob; refuse it
_TEXT_SUFFIXES = {".md", ".txt", ".sql", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".ts", ".tsx",
                  ".js", ".mjs", ".cjs", ".py", ".java", ".graphql", ".csv", ".properties", ".html", ".htm",
                  ".xml", ".sh", ".bash", ".css", ".scss", ".proto", ".tf", ".hcl", ".example", ".svelte"}
# Extensionless files that are still text and carry facts.
_TEXT_NAMES = {"CODEOWNERS", "Dockerfile", "Makefile", "LICENSE", "Procfile", "Vagrantfile"}
_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build", ".next", ".mypy_cache", ".agents"}

# The CLI vocabulary for a declared root. `SourceType` values are what a claim records;
# this mapping is the only place the two vocabularies meet.
KINDS: dict[str, SourceType] = {
    "adr": SourceType.ADR,
    "api-specs": SourceType.API_SPEC,
    "code": SourceType.CODE,
    "config": SourceType.CONFIG,
    "docs": SourceType.DESIGN_DOC,
    "sql": SourceType.SCHEMA,
}

PROBE_SAMPLE = 400  # files a probe may look at: enough to classify a tree, never a full index
_HEAD_LINES = 400  # a header or a first DDL statement lives well inside this


@dataclass(frozen=True)
class Root:
    id: str
    path: Path
    kind: str | None = None  # declared `--source <kind>:<dir>`; None means inferred from paths

    def pointer(self, relative: Path) -> str:
        return f"{self.id}/{relative.as_posix()}"


def root_id(path: Path) -> str:
    """Stable, readable, and safe in a pointer: the directory name, slugged."""
    return re.sub(r"[^a-z0-9_.-]+", "-", path.name.lower()).strip("-") or "root"


def split_typed(arg: str) -> tuple[str | None, Path]:
    """`<kind>:<dir>` or a bare `<dir>`; an unknown kind is an error, never a guess.

    A colon with a slash before it (`/tmp/a:b`) belongs to the path, so only a
    slash-free prefix can be a declared kind (issue 69).
    """
    kind, separator, directory = arg.partition(":")
    if not separator or "/" in kind or "." in kind:
        return None, Path(arg)
    if kind not in KINDS:
        raise ValueError(f"unknown source type {kind!r}; valid types: {', '.join(sorted(KINDS))}")
    if not directory:
        raise ValueError(f"source {arg!r} declares a type but no directory")
    return kind, Path(directory)


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


def iter_files(root: Root, *, claimable: Callable[[Path], bool] | None = None) -> Iterator[tuple[Path, str]]:
    """Yield (relative path, streaming sha256). Sorted for determinism; no file is read whole.

    Text is decided by suffix, then by sniffing the first block, so an unfamiliar
    extension can never hide an artefact. Every refused *file* is named on stderr;
    `_SKIP_DIRS` (third-party and build trees) are pruned by design (issue 84).

    `claimable` is how a pipeline that reads non-text files (an image extractor) is
    reached at all: a path it claims is yielded with its digest and never sniffed. The
    walker keeps no opinion about text — it only asks whether something wants the file,
    so an opt-in module's file count is true rather than silently zero.
    """
    for path in sorted(root.path.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root.path)
        if _SKIP_DIRS & set(relative.parts):
            continue
        if not _looks_text(path) and not (claimable is not None and claimable(path)):
            print(f"skip {root.pointer(relative)}: no UTF-8 text in its first bytes", file=sys.stderr)
            continue
        yield relative, hash_file(path)


def _looks_text(path: Path) -> bool:
    """Allowlisted suffix, or a NUL-free head that decodes as UTF-8."""
    if path.suffix.lower() in _TEXT_SUFFIXES or path.name in _TEXT_NAMES:
        return True
    try:
        with path.open("rb") as handle:
            head = handle.read(1 << 13)
    except OSError:
        return False
    if b"\0" in head:
        return False
    # A cut through a multi-byte codepoint leaves one trailing replacement char, not a binary file.
    return "\ufffd" not in head.decode("utf-8", errors="replace").rstrip("\ufffd")


_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_GIF_MAGIC = (b"GIF87a", b"GIF89a")


def image_size(path: Path) -> tuple[int, int]:
    """(width, height) from the header alone — 24 bytes, no decoder, no dependency.

    A region citation is only meaningful inside the real image, so the gate needs the
    dimensions; reading them here keeps the check out of the image library.
    """
    with path.open("rb") as handle:
        head = handle.read(24)
    if head.startswith(_PNG_MAGIC) and head[12:16] == b"IHDR":
        return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    if head.startswith(_GIF_MAGIC):
        return int.from_bytes(head[6:8], "little"), int.from_bytes(head[8:10], "little")
    raise ValueError(f"{path.name}: not a PNG or GIF; cannot verify a region")


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


def _sample(root: Root) -> list[Path]:
    """Bounded, sorted, skip-dir-pruned walk: a probe never pays for a whole tree."""
    files: list[Path] = []
    pending = [root.path]
    while pending and len(files) < PROBE_SAMPLE:
        directory = pending.pop(0)
        try:
            entries = sorted(directory.iterdir(), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            if len(files) >= PROBE_SAMPLE:
                break
            if entry.is_dir():
                if entry.name not in _SKIP_DIRS:
                    pending.append(entry)
            elif entry.is_file():
                files.append(entry)
    return files


def _head(path: Path) -> str:
    """First lines only: enough for a header, a route or a DDL statement."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return "".join(itertools.islice(handle, _HEAD_LINES))
    except OSError:
        return ""


def _shape(files: list[Path]) -> str:
    """What the sample actually contains, so a mismatch explains itself."""
    if not files:
        return "empty"
    counts = Counter(path.suffix.lower() or "(no suffix)" for path in files)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:6]
    return ", ".join(f"{count} {suffix}" for suffix, count in ordered)


_HEADING = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)
_ADR_STATUS = re.compile(r"^\s*(?:[-*]\s*)?\**Status\**\s*:", re.IGNORECASE | re.MULTILINE)
_ADR_SECTION = re.compile(r"^#{1,6}\s+.*\b(decision|context|consequences|rationale)\b", re.IGNORECASE | re.MULTILINE)
_API_KEY = re.compile(r'(?:^|[{,]\s*)["\']?(?:openapi|swagger)["\']?\s*:', re.IGNORECASE | re.MULTILINE)
_API_PATHS = re.compile(r'(?:^|[{,]\s*)["\']?paths["\']?\s*:', re.IGNORECASE | re.MULTILINE)
_API_TEMPLATE = re.compile(r'^\s*["\']/[\w{}/.:-]*["\']\s*:', re.MULTILINE)  # a path key, not tsconfig `paths`
_API_ROUTE = re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+/[\w{}/.:-]+")
_DDL = re.compile(r"\b(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX|VIEW)\b", re.IGNORECASE)
_CONFIG_LINE = re.compile(r'^\s*(?:"?[A-Za-z0-9_.-]+"?\s*[:=]\s*\S|-\s*[A-Za-z0-9_.-]+\s*:\s*\S)', re.MULTILINE)
_CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".jsx", ".java", ".kt", ".go", ".rs", ".rb",
                  ".php", ".cs", ".c", ".cc", ".cpp", ".h", ".hpp", ".swift", ".scala", ".sh", ".graphql"}


def _probe_adr(files: list[Path]) -> tuple[bool, str]:
    """Markdown carrying a heading plus a `Status:` line or a decision-shaped section."""
    markdown = [path for path in files if path.suffix.lower() == ".md"]
    if not markdown:
        return False, f"no markdown files to read (contents: {_shape(files)})"
    for path in markdown:
        head = _head(path)
        if _HEADING.search(head) and (_ADR_STATUS.search(head) or _ADR_SECTION.search(head)):
            return True, path.name
    return False, f"no ADR shape (heading plus Status: or a decision section) in {len(markdown)} markdown files"


def _probe_api_specs(files: list[Path]) -> tuple[bool, str]:
    candidates = [path for path in files if path.suffix.lower() in {".yaml", ".yml", ".json", ".md", ".graphql", ".ts"}]
    if not candidates:
        return False, f"no spec-like files (contents: {_shape(files)})"
    for path in candidates:
        head = _head(path)
        if _API_KEY.search(head) or _API_ROUTE.search(head) or (_API_PATHS.search(head) and _API_TEMPLATE.search(head)):
            return True, path.name
    return False, f"no route (`POST /v1/...`) or OpenAPI key in {len(candidates)} candidate files"


def _probe_sql(files: list[Path]) -> tuple[bool, str]:
    statements = [path for path in files if path.suffix.lower() in {".sql", ".ddl", ".psql"}]
    if not statements:
        return False, f"no SQL files (contents: {_shape(files)})"
    for path in statements:
        if _DDL.search(_head(path)):
            return True, path.name
    return False, f"no CREATE/ALTER/DROP TABLE statement in {len(statements)} SQL files"


def _probe_config(files: list[Path]) -> tuple[bool, str]:
    candidates = [path for path in files
                  if path.suffix.lower() in {".yaml", ".yml", ".json", ".toml", ".ini", ".properties", ".env"}
                  or path.name.startswith(".env")]
    if not candidates:
        return False, f"no config files (contents: {_shape(files)})"
    for path in candidates:
        if _CONFIG_LINE.search(_head(path)):
            return True, path.name
    return False, f"no name -> value mapping in {len(candidates)} config files"


def _probe_docs(files: list[Path]) -> tuple[bool, str]:
    markdown = [path for path in files if path.suffix.lower() == ".md"]
    if markdown:
        return True, f"{len(markdown)} markdown files"
    return False, f"no markdown files (contents: {_shape(files)})"


def _probe_code(files: list[Path]) -> tuple[bool, str]:
    sources = [path for path in files if path.suffix.lower() in _CODE_SUFFIXES]
    if sources:
        return True, f"{len(sources)} source files"
    return False, f"no source files (contents: {_shape(files)})"


_PROBES = {
    "adr": _probe_adr,
    "api-specs": _probe_api_specs,
    "code": _probe_code,
    "config": _probe_config,
    "docs": _probe_docs,
    "sql": _probe_sql,
}


def probe(kind: str, root: Root) -> tuple[bool, str]:
    """Does `root` contain what `kind` claims? (`ok`, reason naming what was found) (issue 69).

    Pure filesystem work: no graph, no extraction, no model — so a mismatch is cheap and
    the reason can be asserted in a unit test.
    """
    if kind not in _PROBES:
        raise ValueError(f"unknown source type {kind!r}; valid types: {', '.join(sorted(KINDS))}")
    return _PROBES[kind](_sample(root))


class SpanStore:
    """Turns a stored pointer back into bytes, and refuses to leave any registered root."""

    def __init__(self, roots: Iterable[Root], fallback: Path | None = None) -> None:
        self._roots = {r.id: r.path.resolve() for r in roots}
        self._hashes: dict[str, str] = {}
        if fallback is not None:
            self._roots.setdefault("", Path(fallback).resolve())

    def _base(self, pointer: str) -> tuple[Path, str]:
        """`<root>/<rel>` when the root is known; a bare path is resolved against any root.

        Bare pointers are what reviewed fixtures use, and they must keep working after a
        second corpus is mounted, so existence decides rather than root count.
        """
        identifier, _, relative = pointer.partition("/")
        if identifier in self._roots:
            return self._roots[identifier], relative
        for base in self._roots.values():
            if (base / pointer).exists():  # a directory is a refused path, not a missing one
                return base, pointer
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

    def read_region(self, pointer: str, region: tuple[int, int, int, int]) -> bytes:
        """The rectangle of an image, in its own format — decoded as text only if hopeless.

        A citation of a picture must resolve to pixels. Cropping needs Pillow, which the
        default install does not carry: without it the whole file is returned rather than a
        text decode of PNG bytes, which would "verify" against the wrong thing.
        """
        path = self.resolve(pointer)
        width, height = image_size(path)
        x, y, w, h = region
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise ValueError(f"region {region} escapes the {width}x{height} image")
        try:
            from PIL import Image
        except ImportError:
            return path.read_bytes()
        with Image.open(path) as image:
            return _png_bytes(image.crop((x, y, x + w, y + h)))


def _png_bytes(image) -> bytes:
    """PNG in memory, whichever format the crop came from."""
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
