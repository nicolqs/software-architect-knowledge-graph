"""TypeScript extractor via tree-sitter (Rust bindings via tree-sitter-language-pack)."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any

from tree_sitter_language_pack import get_parser

from architect.ingest.parsers._common import (
    content_hash,
    end_line_of,
    iter_children,
    line_of,
    loc,
    text,
    ts_module_qname,
)
from architect.ingest.types import ParsedCall, ParsedDef, ParsedFile, ParsedImport

_parser_ts = get_parser("typescript")
_parser_tsx = get_parser("tsx")


def parse_typescript(*, repo: str, rel_path: str, source: bytes) -> ParsedFile:
    parser = _parser_tsx if PurePosixPath(rel_path).suffix.lower() == ".tsx" else _parser_ts
    src_str = source.decode("utf-8", errors="replace")
    tree = parser.parse(src_str)
    assert tree is not None
    module_qname = ts_module_qname(rel_path)
    pf = ParsedFile(
        repo=repo,
        path=rel_path,
        language="typescript",
        content_hash=content_hash(source),
        loc=loc(source),
        module_qname=module_qname,
    )
    root = tree.root_node()
    for child in iter_children(root):
        _walk(child, src_str, module_qname, pf, enclosing_func=None)
    return pf


def _walk(
    node: Any,
    source: str,
    parent_qname: str,
    pf: ParsedFile,
    *,
    enclosing_func: str | None,
) -> None:
    kind = node.kind()
    if kind == "import_statement":
        _collect_import(node, source, pf)
    elif kind in ("function_declaration", "generator_function_declaration"):
        _collect_function(node, source, parent_qname, pf)
    elif kind == "class_declaration":
        _collect_class(node, source, parent_qname, pf)
    elif kind in ("lexical_declaration", "variable_declaration"):
        _collect_named_function_expr(node, source, parent_qname, pf)
    elif kind == "export_statement":
        for c in iter_children(node):
            _walk(c, source, parent_qname, pf, enclosing_func=enclosing_func)
    elif kind == "call_expression" and enclosing_func is not None:
        _collect_call(node, source, enclosing_func, pf)
    else:
        for child in iter_children(node):
            _walk(child, source, parent_qname, pf, enclosing_func=enclosing_func)


def _collect_import(node: Any, source: str, pf: ParsedFile) -> None:
    src_node = node.child_by_field_name("source")
    if src_node is None:
        return
    raw = text(src_node, source).strip()
    if len(raw) >= 2 and raw[0] in {'"', "'"} and raw[-1] == raw[0]:
        raw = raw[1:-1]
    names: list[str] = []
    for c in iter_children(node):
        if c.kind() != "import_clause":
            continue
        for cc in iter_children(c):
            tt = cc.kind()
            if tt == "identifier":
                names.append(text(cc, source))
            elif tt == "named_imports":
                for spec in iter_children(cc):
                    if spec.kind() != "import_specifier":
                        continue
                    name_node = spec.child_by_field_name("name")
                    if name_node is None and spec.child_count() > 0:
                        name_node = spec.child(0)
                    if name_node is not None:
                        names.append(text(name_node, source))
            elif tt == "namespace_import":
                ident = next(
                    (x for x in iter_children(cc) if x.kind() == "identifier"), None
                )
                if ident is not None:
                    names.append(text(ident, source))
    pf.imports.append(ParsedImport(source=raw, names=tuple(names), line=line_of(node)))


def _collect_function(node: Any, source: str, parent_qname: str, pf: ParsedFile) -> None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return
    name = text(name_node, source)
    qname = f"{parent_qname}::{name}"
    params = node.child_by_field_name("parameters")
    body = node.child_by_field_name("body")
    pf.definitions.append(
        ParsedDef(
            qname=qname,
            name=name,
            kind="function",
            line=line_of(node),
            end_line=end_line_of(node),
            parent_qname=parent_qname if "::" in parent_qname else None,
            is_async=any(c.kind() == "async" for c in iter_children(node)),
            signature=f"{name}{text(params, source) if params is not None else '()'}",
            body_text=text(body, source) if body is not None else "",
        )
    )
    if body is not None:
        for c in iter_children(body):
            _walk(c, source, qname, pf, enclosing_func=qname)


def _collect_class(node: Any, source: str, parent_qname: str, pf: ParsedFile) -> None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return
    name = text(name_node, source)
    qname = f"{parent_qname}::{name}"
    body = node.child_by_field_name("body")
    pf.definitions.append(
        ParsedDef(
            qname=qname,
            name=name,
            kind="class",
            line=line_of(node),
            end_line=end_line_of(node),
            parent_qname=parent_qname if "::" in parent_qname else None,
            body_text=text(body, source) if body is not None else "",
        )
    )
    if body is None:
        return
    for member in iter_children(body):
        if member.kind() == "method_definition":
            _collect_method(member, source, qname, pf)
        else:
            _walk(member, source, qname, pf, enclosing_func=None)


def _collect_method(node: Any, source: str, class_qname: str, pf: ParsedFile) -> None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return
    name = text(name_node, source)
    qname = f"{class_qname}::{name}"
    params = node.child_by_field_name("parameters")
    body = node.child_by_field_name("body")
    pf.definitions.append(
        ParsedDef(
            qname=qname,
            name=name,
            kind="function",
            line=line_of(node),
            end_line=end_line_of(node),
            parent_qname=class_qname,
            is_async=any(c.kind() == "async" for c in iter_children(node)),
            signature=f"{name}{text(params, source) if params is not None else '()'}",
            body_text=text(body, source) if body is not None else "",
        )
    )
    if body is not None:
        for c in iter_children(body):
            _walk(c, source, qname, pf, enclosing_func=qname)


def _collect_named_function_expr(
    node: Any, source: str, parent_qname: str, pf: ParsedFile
) -> None:
    """Capture `const foo = () => {...}` and `const foo = function () {...}`."""
    for c in iter_children(node):
        if c.kind() != "variable_declarator":
            continue
        name_node = c.child_by_field_name("name")
        value_node = c.child_by_field_name("value")
        if name_node is None or value_node is None:
            continue
        if value_node.kind() not in ("arrow_function", "function_expression", "function"):
            continue
        if name_node.kind() != "identifier":
            continue
        name = text(name_node, source)
        qname = f"{parent_qname}::{name}"
        params = value_node.child_by_field_name("parameters")
        body = value_node.child_by_field_name("body")
        pf.definitions.append(
            ParsedDef(
                qname=qname,
                name=name,
                kind="function",
                line=line_of(c),
                end_line=end_line_of(c),
                parent_qname=parent_qname if "::" in parent_qname else None,
                is_async=any(cc.kind() == "async" for cc in iter_children(value_node)),
                signature=f"{name}{text(params, source) if params is not None else '()'}",
                body_text=text(body, source) if body is not None else "",
            )
        )
        if body is not None:
            for cc in iter_children(body):
                _walk(cc, source, qname, pf, enclosing_func=qname)


def _collect_call(node: Any, source: str, enclosing_func: str, pf: ParsedFile) -> None:
    fn_node = node.child_by_field_name("function")
    if fn_node is None:
        return
    called = text(fn_node, source).strip()
    if not called:
        return
    pf.calls.append(
        ParsedCall(caller_qname=enclosing_func, called_name=called, line=line_of(node))
    )
