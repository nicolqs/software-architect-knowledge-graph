"""Detect source roots so qnames match how the code actually imports.

The problem: when ingesting from a monorepo root, a file at
`apps/api/src/architect/config.py` was getting qname
`apps.api.src.architect.config`. But Python imports in the code are
written as `from architect.config import ...` because
`apps/api/src/` is on PYTHONPATH (via hatch's
`packages = ["src/architect"]`). The resolver couldn't reconcile the two,
so cross-file calls dropped to confidence 0.3-0.5 and most internal
functions appeared dead.

The fix: pre-walk every `pyproject.toml` (and `tsconfig.json`) to learn
the project's source roots. When computing a file's qname, strip the
source-root prefix first.

Supported configs:
- Python: hatch (`tool.hatch.build.targets.wheel.packages`),
  setuptools (`tool.setuptools.packages.find.where`), poetry
  (`tool.poetry.packages.from`), or the heuristic `src/` directory next
  to any pyproject.toml.
- TypeScript: `compilerOptions.baseUrl` in tsconfig.json. Defaults to the
  tsconfig's own directory when absent.

If no config is found, we fall back to repo-root qnames (the v0 behavior),
so an ingest of a one-off script still works.
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import structlog

log = structlog.get_logger()


@dataclass(slots=True)
class SourceRoot:
    """An absolute path that should be treated as `sys.path` for qname purposes.

    `language` lets a file pick the right root if multiple match.
    """

    abs_path: Path
    language: str  # 'python' | 'typescript'


_PYTHON_SUFFIXES = (".py",)
_TS_SUFFIXES = (".ts", ".tsx", ".mts", ".cts")


def detect_source_roots(repo_root: Path) -> list[SourceRoot]:
    """Walk repo_root looking for project configs, return all source roots.

    Multiple are possible in a monorepo (apps/api/src + apps/web/src, etc.).
    Caller sorts by specificity when picking which one applies to a file.
    """
    roots: list[SourceRoot] = []
    for config in _iter_configs(repo_root):
        if config.name == "pyproject.toml":
            roots.extend(_python_roots_from_pyproject(config))
        elif config.name == "tsconfig.json":
            roots.extend(_typescript_roots_from_tsconfig(config))
    # Heuristic fallback: any plain `src/` directory next to a pyproject.toml
    # is also a Python source root, even if the pyproject didn't declare it.
    # Don't double-add.
    seen = {(r.abs_path, r.language) for r in roots}
    for pp in _iter_configs(repo_root):
        if pp.name != "pyproject.toml":
            continue
        candidate = pp.parent / "src"
        if candidate.is_dir() and (candidate, "python") not in seen:
            roots.append(SourceRoot(abs_path=candidate, language="python"))
            seen.add((candidate, "python"))
    log.info("source_roots_detected", count=len(roots))
    return roots


def _iter_configs(repo_root: Path) -> Iterable[Path]:
    """Find pyproject.toml + tsconfig.json files, skipping noisy dirs."""
    skip = {".git", "node_modules", ".venv", "venv", "dist", "build", ".next"}
    stack: list[Path] = [repo_root]
    while stack:
        cur = stack.pop()
        try:
            for entry in cur.iterdir():
                if entry.is_dir() and entry.name not in skip:
                    stack.append(entry)
                elif entry.is_file() and entry.name in ("pyproject.toml", "tsconfig.json"):
                    yield entry
        except PermissionError:
            continue


def _python_roots_from_pyproject(pyproject: Path) -> list[SourceRoot]:
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []

    roots: list[Path] = []

    # Hatch: tool.hatch.build.targets.wheel.packages = ["src/architect"]
    hatch_pkgs = (
        data.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("packages", [])
    )
    for pkg in hatch_pkgs:
        # "src/architect" → the root is "src"; "architect" → root is "."
        parts = PurePosixPath(pkg).parts
        if len(parts) > 1:
            roots.append((pyproject.parent / Path(*parts[:-1])).resolve())
        else:
            roots.append(pyproject.parent.resolve())

    # setuptools: tool.setuptools.packages.find.where = ["src"]
    setuptools_where = (
        data.get("tool", {})
        .get("setuptools", {})
        .get("packages", {})
        .get("find", {})
        .get("where", [])
    )
    for w in setuptools_where:
        roots.append((pyproject.parent / w).resolve())

    # Poetry: tool.poetry.packages = [{ include = "x", from = "src" }]
    poetry_pkgs = data.get("tool", {}).get("poetry", {}).get("packages", [])
    for entry in poetry_pkgs:
        if isinstance(entry, dict) and "from" in entry:
            roots.append((pyproject.parent / entry["from"]).resolve())

    # Deduplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for r in roots:
        if r not in seen and r.is_dir():
            seen.add(r)
            unique.append(r)
    return [SourceRoot(abs_path=r, language="python") for r in unique]


def _typescript_roots_from_tsconfig(tsconfig: Path) -> list[SourceRoot]:
    try:
        raw = tsconfig.read_text(encoding="utf-8")
        # tsconfig.json is JSON-with-comments in many projects; do a best-effort
        # strip of // and /* */ before json.loads.
        cleaned = _strip_json_comments(raw)
        data = json.loads(cleaned)
    except (OSError, json.JSONDecodeError):
        return []

    base = (data.get("compilerOptions") or {}).get("baseUrl")
    if not base:
        return []
    abs_path = (tsconfig.parent / base).resolve()
    if not abs_path.is_dir():
        return []
    return [SourceRoot(abs_path=abs_path, language="typescript")]


def _strip_json_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n:
            nxt = text[i + 1]
            if nxt == "/":
                # line comment
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if nxt == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def qname_relative_path(abs_file: Path, source_roots: list[SourceRoot], repo_root: Path) -> str:
    """Return the posix-style path used to compute a qname.

    Picks the most-specific (longest) matching source root for the file's
    language. Falls back to the path relative to repo_root if no root matches.
    """
    suffix = abs_file.suffix.lower()
    if suffix in _PYTHON_SUFFIXES:
        lang = "python"
    elif suffix in _TS_SUFFIXES:
        lang = "typescript"
    else:
        lang = ""

    # Most-specific root wins (deepest abs_path that is a parent of abs_file).
    best: SourceRoot | None = None
    for root in source_roots:
        if root.language != lang:
            continue
        try:
            abs_file.relative_to(root.abs_path)
        except ValueError:
            continue
        if best is None or len(str(root.abs_path)) > len(str(best.abs_path)):
            best = root

    if best is not None:
        return abs_file.relative_to(best.abs_path).as_posix()
    # Fallback: relative to repo root.
    try:
        return abs_file.relative_to(repo_root).as_posix()
    except ValueError:
        return abs_file.as_posix()


__all__ = [
    "SourceRoot",
    "detect_source_roots",
    "qname_relative_path",
]
