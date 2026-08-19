from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vo_backup.config import BackupConfig
from vo_backup.paths import LocalFile
from vo_backup.sync import _sync_one_file
from vo_backup.vospace import RemoteFile, VOSpace


@pytest.fixture
def config(tmp_path: Path) -> BackupConfig:
    src = tmp_path / "data"
    src.mkdir()
    return BackupConfig(
        job_name="t",
        vospace_root="vos:user/backup",
        source_paths=[src],
        certfile=tmp_path / "c.pem",
    )


def test_sync_links_to_latest_when_missing_from_current(tmp_path: Path, config: BackupConfig):
    f = tmp_path / "data" / "a.txt"
    f.write_text("hello")
    local = LocalFile("data/a.txt", f, 5, f.stat().st_mtime)
    digest = "5d41402abc4b2a76b9719d911017c592"
    snap = RemoteFile("data/a.txt", "vos:user/backup/snapshots/latest/data/a.txt", 5, 0, md5=digest)

    vos = MagicMock(spec=VOSpace)
    vos.remote_uri.return_value = "vos:user/backup/current/data/a.txt"
    vos.fix_uri.side_effect = lambda u: u

    action, _ = _sync_one_file(vos, config, local, None, snap, False, False)
    assert action == "linked"
    vos.link.assert_called_once_with(
        "vos:user/backup/snapshots/latest/data/a.txt",
        "vos:user/backup/current/data/a.txt",
        dry_run=False,
    )


def test_sync_replaces_link_without_touching_snapshot(tmp_path: Path, config: BackupConfig):
    f = tmp_path / "data" / "a.txt"
    f.write_text("changed")
    local = LocalFile("data/a.txt", f, 7, f.stat().st_mtime)
    current = RemoteFile(
        "data/a.txt",
        "vos:user/backup/current/data/a.txt",
        5,
        0,
        is_link=True,
        link_target="vos:user/backup/snapshots/latest/data/a.txt",
    )
    target = RemoteFile(
        "a.txt",
        "vos:user/backup/snapshots/latest/data/a.txt",
        5,
        0,
        md5="5d41402abc4b2a76b9719d911017c592",
    )

    vos = MagicMock(spec=VOSpace)
    vos.remote_uri.return_value = current.uri
    vos.fix_uri.side_effect = lambda u: u
    vos.get_node_info.return_value = target

    action, nbytes = _sync_one_file(vos, config, local, current, None, False, False)
    assert action == "uploaded"
    assert nbytes == 7
    vos.delete.assert_called_once_with(current.uri, dry_run=False)
    vos.copy_local.assert_called_once()
    vos.link.assert_not_called()
