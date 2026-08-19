from pathlib import Path

from vo_backup.paths import build_matcher, iter_local_files


def test_iter_local_files_include_exclude(tmp_path: Path):
    src = tmp_path / "project"
    src.mkdir()
    (src / "keep.txt").write_text("a")
    (src / "skip.tmp").write_text("b")
    git = src / ".git"
    git.mkdir()
    (git / "obj").write_text("c")

    files = iter_local_files(
        [src],
        include=["**/*"],
        exclude=["**/*.tmp", "**/.git/**"],
    )
    rels = {f.rel_path for f in files}
    assert rels == {"project/keep.txt"}


def test_build_matcher():
    spec = build_matcher(["**/*"], ["**/node_modules/**"])
    assert spec.match_file("src/a.py")
    assert not spec.match_file("src/node_modules/pkg/index.js")
