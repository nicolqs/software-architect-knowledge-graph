"""File walker that respects .gitignore and a few hard skip rules."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pathspec

from architect.ingest.parsers import language_for

# Always skipped — pathspec would skip these too if .gitignore listed them,
# but most repos don't bother and these dirs explode walk time.
_ALWAYS_SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".next",
        ".turbo",
        ".vite",
        "target",
        ".data",
    }
)

_MAX_FILE_BYTES = 1_000_000  # skip files >1MB (vendored bundles, lockfiles, etc.)


def _load_gitignore(root: Path) -> pathspec.PathSpec[Any]:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return pathspec.PathSpec.from_lines("gitignore", [])
    return pathspec.PathSpec.from_lines("gitignore", gitignore.read_text().splitlines())


def walk_repo(root: Path, *, limit: int | None = None) -> Iterator[tuple[str, bytes]]:
    """Yield (rel_path, bytes) for every supported source file under root.

    rel_path is posix-style and relative to root.
    """
    spec = _load_gitignore(root)
    yielded = 0
    for path in _iter_files(root, spec):
        rel = path.relative_to(root).as_posix()
        if language_for(rel) is None:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if len(data) > _MAX_FILE_BYTES:
            continue
        yield rel, data
        yielded += 1
        if limit is not None and yielded >= limit:
            return


def _iter_files(root: Path, spec: pathspec.PathSpec[Any]) -> Iterator[Path]:
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(current.iterdir())
        except PermissionError:
            continue
        for entry in entries:
            name = entry.name
            if entry.is_dir():
                if name in _ALWAYS_SKIP_DIRS:
                    continue
                rel = entry.relative_to(root).as_posix()
                if spec.match_file(rel + "/"):
                    continue
                stack.append(entry)
            elif entry.is_file():
                rel = entry.relative_to(root).as_posix()
                if spec.match_file(rel):
                    continue
                yield entry
