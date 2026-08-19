from pathlib import Path
from unittest.mock import MagicMock

from vo_backup.md5_util import file_md5
from vo_backup.paths import LocalFile
from vo_backup.snapshot_dedup import canonical_data_uri, unchanged_for_snapshot
from vo_backup.vospace import RemoteFile


def test_unchanged_by_md5(tmp_path: Path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"same-content")
    local = LocalFile("p/f.bin", f, f.stat().st_size, f.stat().st_mtime)
    digest = file_md5(f)
    prev = RemoteFile("p/f.bin", "vos:u/snap/old/p/f.bin", f.stat().st_size, 0, md5=digest)
    assert unchanged_for_snapshot(local, prev, None) is True


def test_unchanged_false_when_no_prev(tmp_path: Path):
    f = tmp_path / "f.bin"
    f.write_bytes(b"x")
    local = LocalFile("f.bin", f, 1, 0)
    assert unchanged_for_snapshot(local, None, None) is False


def test_canonical_data_uri_link():
    prev = RemoteFile(
        "a",
        "vos:u/old/a",
        1,
        0,
        is_link=True,
        link_target="vos:u/new/a",
    )
    assert canonical_data_uri(prev) == "vos:u/new/a"


def test_canonical_data_uri_data():
    prev = RemoteFile("a", "vos:u/old/a", 1, 0)
    assert canonical_data_uri(prev) == "vos:u/old/a"
