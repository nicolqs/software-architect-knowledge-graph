"""Typed dataclasses produced by parsers and consumed by the graph writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Language = Literal["python", "typescript"]
DefKind = Literal["function", "class"]


@dataclass(slots=True)
class ParsedDef:
    qname: str
    name: str
    kind: DefKind
    line: int
    end_line: int
    parent_qname: str | None = None  # set for methods (parent is the Class qname)
    is_async: bool = False
    signature: str = ""
    body_text: str = ""  # used for embedding


@dataclass(slots=True)
class ParsedImport:
    """A single import statement entry.

    `source` is the raw module string from the source ('foo.bar' / './utils' / '@scope/pkg').
    `names` are the imported symbol names (empty for plain `import foo`; then `foo` is the name).
    `line` is 1-indexed.
    """

    source: str
    names: tuple[str, ...]
    line: int


@dataclass(slots=True)
class ParsedCall:
    caller_qname: str  # qname of the Function that contains the call site
    called_name: str   # the raw name/attribute as written ('foo.bar' or 'baz')
    line: int


@dataclass(slots=True)
class ParsedFile:
    repo: str
    path: str  # relative to repo root, posix-style
    language: Language
    content_hash: str
    loc: int
    module_qname: str
    definitions: list[ParsedDef] = field(default_factory=list)
    imports: list[ParsedImport] = field(default_factory=list)
    calls: list[ParsedCall] = field(default_factory=list)
