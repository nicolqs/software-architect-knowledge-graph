"""Language dispatch for parsers."""

from __future__ import annotations

from pathlib import PurePosixPath

from architect.ingest.parsers.python import parse_python
from architect.ingest.parsers.typescript import parse_typescript
from architect.ingest.types import Language, ParsedFile

_PY_SUFFIXES = {".py"}
_TS_SUFFIXES = {".ts", ".tsx", ".mts", ".cts"}


def language_for(path: str) -> Language | None:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in _PY_SUFFIXES:
        return "python"
    if suffix in _TS_SUFFIXES:
        return "typescript"
    return None


def parse_file(
    *,
    repo: str,
    rel_path: str,
    source: bytes,
) -> ParsedFile | None:
    """Parse a file given its bytes. Returns None if the language is unsupported."""
    lang = language_for(rel_path)
    if lang == "python":
        return parse_python(repo=repo, rel_path=rel_path, source=source)
    if lang == "typescript":
        return parse_typescript(repo=repo, rel_path=rel_path, source=source)
    return None
