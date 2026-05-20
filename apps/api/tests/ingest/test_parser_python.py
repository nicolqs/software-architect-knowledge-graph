from architect.ingest.parsers.python import parse_python

SAMPLE = b'''
import os
from typing import Any

from .sibling import helper


def top_level(x: int) -> int:
    return helper(x) + os.cpu_count()


class Greeter:
    def __init__(self, name: str) -> None:
        self.name = name

    async def greet(self) -> str:
        return f"hi {self.name}"


def calls_method() -> None:
    g = Greeter("nico")
    g.greet()
'''


def test_extracts_module_and_definitions() -> None:
    pf = parse_python(repo="demo", rel_path="pkg/mod.py", source=SAMPLE)
    assert pf.module_qname == "pkg.mod"
    names = {d.qname: d for d in pf.definitions}
    assert "pkg.mod.top_level" in names
    assert "pkg.mod.Greeter" in names
    assert "pkg.mod.Greeter.__init__" in names
    assert "pkg.mod.Greeter.greet" in names
    assert names["pkg.mod.Greeter.greet"].is_async is True


def test_extracts_imports() -> None:
    pf = parse_python(repo="demo", rel_path="pkg/mod.py", source=SAMPLE)
    sources = sorted({imp.source for imp in pf.imports})
    assert "os" in sources
    assert "typing" in sources
    assert ".sibling" in sources


MULTIBYTE = b'''
# A docstring with an em-dash \xe2\x80\x94 forces multibyte offsets.

def graph_client_init() -> None:
    pass


def caller() -> None:
    graph_client_init()
'''


def test_multibyte_does_not_corrupt_names() -> None:
    """Regression: tree-sitter byte_range is in UTF-8 bytes, not str chars.

    Before the fix, slicing the decoded str with byte offsets silently
    shifted identifier text after any multibyte character. We assert the
    extracted def + call names are exact, not subtly shifted.
    """
    pf = parse_python(repo="demo", rel_path="pkg/mb.py", source=MULTIBYTE)
    qnames = {d.qname for d in pf.definitions}
    assert "pkg.mb.graph_client_init" in qnames
    assert "pkg.mb.caller" in qnames
    called = {c.called_name for c in pf.calls}
    assert called == {"graph_client_init"}


def test_extracts_calls() -> None:
    pf = parse_python(repo="demo", rel_path="pkg/mod.py", source=SAMPLE)
    callers = {c.caller_qname for c in pf.calls}
    # `top_level` calls helper and os.cpu_count; `calls_method` calls Greeter and g.greet.
    assert "pkg.mod.top_level" in callers
    assert "pkg.mod.calls_method" in callers
    # Make sure call names captured the attribute form.
    names = {c.called_name for c in pf.calls if c.caller_qname == "pkg.mod.top_level"}
    assert "helper" in names
    assert "os.cpu_count" in names
