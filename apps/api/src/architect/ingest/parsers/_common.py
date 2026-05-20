"""Shared helpers for tree-sitter extractors.

tree-sitter-language-pack 1.8.1 ships the new Rust-binding API where
attributes are methods (e.g. `node.kind()`, not `.type`), `parser.parse`
takes a `str`, and child traversal goes through `.child(i)` /
`.child_count()`. We isolate that mismatch in this module.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import PurePosixPath
from typing import Any


def content_hash(source: bytes) -> str:
    return hashlib.sha256(source).hexdigest()


def loc(source: bytes) -> int:
    if not source:
        return 0
    return source.count(b"\n") + (0 if source.endswith(b"\n") else 1)


def text(node: Any, source: bytes) -> str:
    """Slice the original bytes by the node's byte range, then decode.

    Tree-sitter's `byte_range` is always in UTF-8 bytes — even when we hand
    `parser.parse(str)` a Python string, the offsets index the encoded buffer,
    not the Python code points. Slicing the decoded `str` directly is wrong
    as soon as the file contains any multibyte character (em-dashes etc.)
    and silently corrupts call-name and identifier extraction.
    """
    rng = node.byte_range()
    return source[rng.start : rng.end].decode("utf-8", errors="replace")


def line_of(node: Any) -> int:
    return int(node.start_position().row) + 1


def end_line_of(node: Any) -> int:
    return int(node.end_position().row) + 1


def iter_children(node: Any) -> Iterator[Any]:
    for i in range(node.child_count()):
        yield node.child(i)


def python_module_qname(rel_path: str) -> str:
    """`foo/bar/baz.py` → `foo.bar.baz`. `foo/__init__.py` → `foo`."""
    p = PurePosixPath(rel_path)
    parts = list(p.parts)
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts:
        parts[-1] = p.stem
    return ".".join(parts)


def ts_module_qname(rel_path: str) -> str:
    """`src/foo/bar.ts` → `src/foo/bar`. `src/foo/index.ts` → `src/foo`."""
    p = PurePosixPath(rel_path)
    parts = list(p.parts)
    stem = p.stem
    if stem == "index" and len(parts) > 1:
        parts = parts[:-1]
    else:
        parts[-1] = stem
    return "/".join(parts)
