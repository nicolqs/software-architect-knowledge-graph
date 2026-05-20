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
    qname_path: str | None = None,
) -> ParsedFile | None:
    """Parse a file given its bytes. Returns None if the language is unsupported.

    `rel_path` is used for the File node's `path` (repo-root-relative).
    `qname_path` is used to compute module/function/class qnames; pass the
    path stripped of the project's source-root prefix so imports written
    `architect.foo` resolve to qname `architect.foo`. Defaults to rel_path.
    """
    lang = language_for(rel_path)
    qpath = qname_path or rel_path
    if lang == "python":
        return parse_python(repo=repo, rel_path=rel_path, source=source, qname_path=qpath)
    if lang == "typescript":
        return parse_typescript(repo=repo, rel_path=rel_path, source=source, qname_path=qpath)
    return None
