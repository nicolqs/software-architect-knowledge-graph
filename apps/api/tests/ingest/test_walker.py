from pathlib import Path

from architect.ingest.walker import walk_repo


def test_walker_includes_py_and_ts_skips_dirs_and_large(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.ts").write_text("export const x = 1;\n")
    (tmp_path / "c.txt").write_text("not a source file\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.ts").write_text("noop\n")
    (tmp_path / "deep").mkdir()
    (tmp_path / "deep" / "inner.tsx").write_text("export default null;\n")
    (tmp_path / "big.py").write_bytes(b"x = 1\n" * 200_000)  # >1MB

    found = {rel for rel, _ in walk_repo(tmp_path)}
    assert "a.py" in found
    assert "b.ts" in found
    assert "deep/inner.tsx" in found
    assert "node_modules/ignored.ts" not in found
    assert "c.txt" not in found
    assert "big.py" not in found


def test_walker_respects_gitignore(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.py\n")
    (tmp_path / "kept.py").write_text("x = 1\n")
    (tmp_path / "ignored.py").write_text("x = 1\n")
    found = {rel for rel, _ in walk_repo(tmp_path)}
    assert "kept.py" in found
    assert "ignored.py" not in found
