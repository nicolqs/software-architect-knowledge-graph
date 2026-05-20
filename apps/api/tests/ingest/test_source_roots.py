"""Unit tests for source-root detection.

Each scenario builds a tiny on-disk project and asserts the right roots
are picked up + qname stripping works.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from architect.ingest.source_roots import (
    _strip_json_comments,
    detect_source_roots,
    qname_relative_path,
)


def test_hatch_packages_yields_src_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        dedent(
            """
            [tool.hatch.build.targets.wheel]
            packages = ["src/myapp"]
            """
        )
    )
    (tmp_path / "src" / "myapp").mkdir(parents=True)
    (tmp_path / "src" / "myapp" / "__init__.py").write_text("")

    roots = detect_source_roots(tmp_path)
    py_roots = [r for r in roots if r.language == "python"]
    # Both the hatch declaration and the heuristic-fallback agree on `src`.
    assert any(r.abs_path == (tmp_path / "src").resolve() for r in py_roots)


def test_setuptools_where_yields_src_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        dedent(
            """
            [tool.setuptools.packages.find]
            where = ["src"]
            """
        )
    )
    (tmp_path / "src").mkdir()
    roots = detect_source_roots(tmp_path)
    assert any(r.abs_path == (tmp_path / "src").resolve() for r in roots)


def test_poetry_packages_from_yields_root(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        dedent(
            """
            [tool.poetry]
            name = "x"
            packages = [{include = "x", from = "lib"}]
            """
        )
    )
    (tmp_path / "lib").mkdir()
    roots = detect_source_roots(tmp_path)
    assert any(r.abs_path == (tmp_path / "lib").resolve() for r in roots)


def test_heuristic_src_fallback_without_explicit_config(tmp_path: Path) -> None:
    # pyproject exists but doesn't declare a source root — heuristic should
    # still pick up the conventional `src/` next to it.
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "0"\n')
    (tmp_path / "src").mkdir()
    roots = detect_source_roots(tmp_path)
    py_roots = [r for r in roots if r.language == "python"]
    assert py_roots
    assert py_roots[0].abs_path == (tmp_path / "src").resolve()


def test_tsconfig_base_url_picked_up(tmp_path: Path) -> None:
    (tmp_path / "tsconfig.json").write_text(
        dedent(
            """
            {
              // mostly-stripped comment
              "compilerOptions": {
                "baseUrl": "./src",
                "strict": true /* trailing block */
              }
            }
            """
        )
    )
    (tmp_path / "src").mkdir()
    roots = detect_source_roots(tmp_path)
    ts_roots = [r for r in roots if r.language == "typescript"]
    assert ts_roots
    assert ts_roots[0].abs_path == (tmp_path / "src").resolve()


def test_qname_path_strips_root_prefix(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        dedent(
            """
            [tool.hatch.build.targets.wheel]
            packages = ["src/myapp"]
            """
        )
    )
    (tmp_path / "src" / "myapp").mkdir(parents=True)
    f = tmp_path / "src" / "myapp" / "config.py"
    f.write_text("X = 1\n")
    roots = detect_source_roots(tmp_path)
    qpath = qname_relative_path(f, roots, tmp_path)
    assert qpath == "myapp/config.py"


def test_qname_path_falls_back_to_repo_root_without_match(tmp_path: Path) -> None:
    f = tmp_path / "script.py"
    f.write_text("X = 1\n")
    # No pyproject, no source roots.
    qpath = qname_relative_path(f, [], tmp_path)
    assert qpath == "script.py"


def test_most_specific_root_wins(tmp_path: Path) -> None:
    # Monorepo-like: two configs, two roots. A file under apps/api/src/...
    # should resolve relative to apps/api/src, not the outer repo root.
    (tmp_path / "apps" / "api").mkdir(parents=True)
    (tmp_path / "apps" / "api" / "pyproject.toml").write_text(
        dedent(
            """
            [tool.hatch.build.targets.wheel]
            packages = ["src/architect"]
            """
        )
    )
    (tmp_path / "apps" / "api" / "src" / "architect").mkdir(parents=True)
    f = tmp_path / "apps" / "api" / "src" / "architect" / "config.py"
    f.write_text("X = 1\n")
    roots = detect_source_roots(tmp_path)
    qpath = qname_relative_path(f, roots, tmp_path)
    assert qpath == "architect/config.py"


def test_strip_json_comments_preserves_strings_and_strips_comments() -> None:
    src = dedent(
        """
        {
          "url": "https://example.com/path", // a line comment
          "label": "// not a comment, inside string",
          /* block
             comment */
          "x": 1
        }
        """
    )
    cleaned = _strip_json_comments(src)
    assert "https://example.com/path" in cleaned
    assert "// not a comment" in cleaned
    assert "a line comment" not in cleaned
    assert "block" not in cleaned
