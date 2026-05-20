from architect.ingest.parsers.python import parse_python
from architect.ingest.resolver import resolve

# Two files: `pkg/a.py` defines `helper`; `pkg/b.py` imports + calls it.

A_PY = b'''
def helper(x: int) -> int:
    return x * 2


def local() -> int:
    return helper(3)  # intra-file call (confidence 1.0)
'''

B_PY = b'''
from pkg.a import helper


def consumer() -> int:
    return helper(5)  # cross-file static import (confidence 0.7)


def unknown_call() -> int:
    return mystery()  # unresolved (confidence 0.3)
'''


def test_confidence_scoring() -> None:
    files = [
        parse_python(repo="demo", rel_path="pkg/a.py", source=A_PY),
        parse_python(repo="demo", rel_path="pkg/b.py", source=B_PY),
    ]
    resolved = resolve(files)

    # Build a quick index: (caller, target) -> confidence
    by_pair = {(c.caller_qname, c.target_qname): c.confidence for c in resolved.calls}

    # Intra-file call inside pkg.a
    assert by_pair.get(("pkg.a.local", "pkg.a.helper")) == 1.0
    # Cross-file static-import call from pkg.b → pkg.a.helper
    assert by_pair.get(("pkg.b.consumer", "pkg.a.helper")) == 0.7
    # Unresolved call falls to external::mystery at 0.3
    assert by_pair.get(("pkg.b.unknown_call", "external::mystery")) == 0.3
