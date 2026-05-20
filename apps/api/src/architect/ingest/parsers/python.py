"""Python extractor via tree-sitter (Rust bindings via tree-sitter-language-pack).

Extracts: top-level + nested function defs (incl. methods), classes,
imports, intra-file calls. Call resolution to a target qname happens in
the cross-file resolver pass.
"""

from __future__ import annotations

from typing import Any

from tree_sitter_language_pack import get_parser

from architect.ingest.parsers._common import (
    content_hash,
    end_line_of,
    iter_children,
    line_of,
    loc,
    python_module_qname,
    text,
)
from architect.ingest.types import ParsedCall, ParsedDef, ParsedFile, ParsedImport

_parser = get_parser("python")


def parse_python(*, repo: str, rel_path: str, source: bytes) -> ParsedFile:
    # tree-sitter wants str, but byte_range() is in bytes — see _common.text().
    tree = _parser.parse(source.decode("utf-8", errors="replace"))
    assert tree is not None  # parser.parse only returns None on edit-tree usage
    module_qname = python_module_qname(rel_path)
    pf = ParsedFile(
        repo=repo,
        path=rel_path,
        language="python",
        content_hash=content_hash(source),
        loc=loc(source),
        module_qname=module_qname,
    )
    root = tree.root_node()
    for child in iter_children(root):
        _walk(child, source, module_qname, pf, enclosing_func=None)
    return pf


def _walk(
    node: Any,
    source: bytes,
    parent_qname: str,
    pf: ParsedFile,
    *,
    enclosing_func: str | None,
) -> None:
    kind = node.kind()
    if kind == "import_statement":
        _collect_import(node, source, pf, is_from=False)
    elif kind == "import_from_statement":
        _collect_import(node, source, pf, is_from=True)
    elif kind == "function_definition":
        _collect_function(node, source, parent_qname, pf)
    elif kind == "class_definition":
        _collect_class(node, source, parent_qname, pf)
    elif kind == "call" and enclosing_func is not None:
        _collect_call(node, source, enclosing_func, pf)
    else:
        for child in iter_children(node):
            _walk(child, source, parent_qname, pf, enclosing_func=enclosing_func)


def _collect_import(node: Any, source: bytes, pf: ParsedFile, *, is_from: bool) -> None:
    if is_from:
        module_node = node.child_by_field_name("module_name")
        source_mod = text(module_node, source) if module_node is not None else ""
        names: list[str] = []
        for c in iter_children(node):
            if c is module_node:
                continue
            ck = c.kind()
            if ck == "dotted_name":
                names.append(text(c, source))
            elif ck == "aliased_import":
                inner = c.child_by_field_name("name")
                if inner is not None:
                    names.append(text(inner, source))
        pf.imports.append(ParsedImport(source=source_mod, names=tuple(names), line=line_of(node)))
        return

    for c in iter_children(node):
        ck = c.kind()
        if ck == "dotted_name":
            mod = text(c, source)
            pf.imports.append(
                ParsedImport(source=mod, names=(mod.split(".")[-1],), line=line_of(node))
            )
        elif ck == "aliased_import":
            inner = c.child_by_field_name("name")
            if inner is not None:
                mod = text(inner, source)
                pf.imports.append(
                    ParsedImport(source=mod, names=(mod.split(".")[-1],), line=line_of(node))
                )


def _collect_function(node: Any, source: bytes, parent_qname: str, pf: ParsedFile) -> None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return
    name = text(name_node, source)
    qname = f"{parent_qname}.{name}"
    params_node = node.child_by_field_name("parameters")
    signature = f"{name}{text(params_node, source) if params_node is not None else '()'}"
    is_async = any(c.kind() == "async" for c in iter_children(node))
    body_node = node.child_by_field_name("body")

    pf.definitions.append(
        ParsedDef(
            qname=qname,
            name=name,
            kind="function",
            line=line_of(node),
            end_line=end_line_of(node),
            parent_qname=parent_qname if "." in parent_qname else None,
            is_async=is_async,
            signature=signature,
            body_text=text(body_node, source) if body_node is not None else "",
        )
    )

    if body_node is not None:
        for child in iter_children(body_node):
            _walk(child, source, qname, pf, enclosing_func=qname)


def _collect_class(node: Any, source: bytes, parent_qname: str, pf: ParsedFile) -> None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return
    name = text(name_node, source)
    qname = f"{parent_qname}.{name}"
    body_node = node.child_by_field_name("body")
    pf.definitions.append(
        ParsedDef(
            qname=qname,
            name=name,
            kind="class",
            line=line_of(node),
            end_line=end_line_of(node),
            parent_qname=parent_qname if "." in parent_qname else None,
            body_text=text(body_node, source) if body_node is not None else "",
        )
    )
    if body_node is not None:
        for child in iter_children(body_node):
            _walk(child, source, qname, pf, enclosing_func=None)


def _collect_call(node: Any, source: bytes, enclosing_func: str, pf: ParsedFile) -> None:
    fn_node = node.child_by_field_name("function")
    if fn_node is None:
        return
    called = text(fn_node, source).strip()
    if not called:
        return
    pf.calls.append(
        ParsedCall(caller_qname=enclosing_func, called_name=called, line=line_of(node))
    )
