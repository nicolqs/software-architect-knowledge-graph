"""Cross-file resolution: turn raw call/import names into target qnames + confidence.

Confidence convention:
- 1.0: intra-file definition exists for the called name (no import needed).
- 0.7: cross-file static import resolves the called name to a known def in the repo.
- 0.3: not resolved (dynamic dispatch / external library / fallback).

Edges below 0.5 are advisory only for the PR reviewer (see plan).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from architect.ingest.types import ParsedFile


@dataclass(slots=True)
class ResolvedCall:
    caller_qname: str
    target_qname: str
    confidence: float
    line: int


@dataclass(slots=True)
class ResolvedImport:
    """An IMPORTS edge from a file to a module.

    `target_qname` is always a module qname (so the writer creates a Module
    node, never colliding with Function/Class qnames). When the import named
    a specific symbol that we could resolve, `imported_name` preserves which.
    """

    file_path: str
    target_qname: str
    confidence: float
    line: int
    imported_name: str | None = None  # the specific symbol, if any


@dataclass(slots=True)
class ResolvedRepo:
    calls: list[ResolvedCall] = field(default_factory=list)
    imports: list[ResolvedImport] = field(default_factory=list)


def resolve(files: list[ParsedFile]) -> ResolvedRepo:
    """Resolve calls and imports across all parsed files in a repo.

    Builds a symbol table once, then walks each file's calls/imports to find
    a target qname. Unresolved entries still get an edge at confidence 0.3
    so the graph reflects intent even when we can't prove the target.
    """
    out = ResolvedRepo()
    by_qname: dict[str, str] = {}        # qname → def kind ('function'/'class')
    by_simple_name: dict[str, list[str]] = {}  # last-segment name → list of qnames
    module_files: dict[str, str] = {}    # module_qname → file path
    file_defs: dict[str, set[str]] = {}  # file path → set of def qnames

    for pf in files:
        module_files[pf.module_qname] = pf.path
        file_defs.setdefault(pf.path, set())
        for d in pf.definitions:
            by_qname[d.qname] = d.kind
            file_defs[pf.path].add(d.qname)
            simple = d.qname.replace("::", ".").split(".")[-1]
            by_simple_name.setdefault(simple, []).append(d.qname)

    for pf in files:
        # Build a per-file `imported_name → target_qname` table for resolving
        # calls inside the file.
        imported: dict[str, str] = {}
        for imp in pf.imports:
            resolved_module_qname = _resolve_import_source(pf, imp.source, module_files)
            if resolved_module_qname is None:
                # External or unresolved; still record at low confidence with a
                # synthetic target so the graph shows the dependency intent.
                out.imports.append(
                    ResolvedImport(
                        file_path=pf.path,
                        target_qname=f"external::{imp.source}",
                        confidence=0.3,
                        line=imp.line,
                    )
                )
                continue
            for name in imp.names or ():
                import_target = _join_qname(pf.language, resolved_module_qname, name)
                if import_target in by_qname:
                    # Cache for the per-file call resolver. The IMPORTS edge
                    # itself still points at the *module* (see ResolvedImport).
                    imported[name] = import_target
                    out.imports.append(
                        ResolvedImport(
                            file_path=pf.path,
                            target_qname=resolved_module_qname,
                            confidence=0.7,
                            line=imp.line,
                            imported_name=name,
                        )
                    )
                else:
                    out.imports.append(
                        ResolvedImport(
                            file_path=pf.path,
                            target_qname=resolved_module_qname,
                            confidence=0.5,
                            line=imp.line,
                            imported_name=name,
                        )
                    )

        # Resolve calls. Strategy in priority order:
        # 1. Match against this file's own defs by last-segment name (1.0).
        # 2. Match against this file's `imported` table (0.7).
        # 3. Match against any def in the repo by last-segment name (0.5 if unique, 0.3 if ambiguous).
        # 4. Fallback: external::called_name at 0.3.
        intra_file_names = {
            _last_segment(q): q for q in file_defs.get(pf.path, set())
        }
        for call in pf.calls:
            simple = _last_segment_of_called(call.called_name)
            target: str | None = None
            confidence = 0.3

            if simple in intra_file_names:
                target = intra_file_names[simple]
                confidence = 1.0
            elif simple in imported:
                target = imported[simple]
                confidence = 0.7
            else:
                candidates = by_simple_name.get(simple, [])
                if len(candidates) == 1:
                    target = candidates[0]
                    confidence = 0.5
                elif len(candidates) > 1:
                    target = candidates[0]
                    confidence = 0.3

            if target is None:
                target = f"external::{call.called_name}"
                confidence = 0.3

            out.calls.append(
                ResolvedCall(
                    caller_qname=call.caller_qname,
                    target_qname=target,
                    confidence=confidence,
                    line=call.line,
                )
            )

    return out


def _resolve_import_source(
    pf: ParsedFile,
    source: str,
    module_files: dict[str, str],
) -> str | None:
    """Return the module qname that this import refers to, if intra-repo."""
    if pf.language == "python":
        # Python import paths are already module qnames (dotted).
        if source in module_files:
            return source
        # `from .sibling import X` — relative imports starting with '.'
        if source.startswith("."):
            return _resolve_python_relative(pf.module_qname, source, module_files)
        return None

    # TypeScript: relative paths only. Bare specifiers ('react') are external.
    if not (source.startswith("./") or source.startswith("../") or source.startswith("/")):
        return None
    file_dir = PurePosixPath(pf.path).parent
    resolved = (file_dir / source).as_posix()
    # Try common suffixes.
    candidates = [
        resolved,
        f"{resolved}/index",
        resolved.removesuffix(".ts").removesuffix(".tsx"),
    ]
    for c in candidates:
        if c in module_files:
            return c
    return None


def _resolve_python_relative(
    current_module: str, source: str, module_files: dict[str, str]
) -> str | None:
    dots = 0
    for ch in source:
        if ch == ".":
            dots += 1
        else:
            break
    parts = current_module.split(".")
    # `from .x import y` means same package as current_module's parent.
    base = parts[: max(0, len(parts) - dots)]
    tail = source[dots:]
    candidate = ".".join([*base, *([] if not tail else tail.split("."))]).strip(".")
    return candidate if candidate in module_files else None


def _join_qname(language: str, module_qname: str, name: str) -> str:
    return f"{module_qname}.{name}" if language == "python" else f"{module_qname}::{name}"


def _last_segment(qname: str) -> str:
    return qname.replace("::", ".").split(".")[-1]


def _last_segment_of_called(called: str) -> str:
    # `foo.bar.baz()` → 'baz'; `obj.method` → 'method'; `baz` → 'baz'.
    return called.split(".")[-1].split("(")[0]
