from pathlib import Path
from unittest.mock import MagicMock

from vo_backup.config import BackupConfig
from vo_backup.sync import _needs_upload
from vo_backup.vospace import RemoteFile


def test_needs_upload_new_file():
    local = MagicMock(size=100, mtime=1000.0)
    assert _needs_upload(local, None, False) is True


def test_needs_upload_same_size_and_mtime():
    local = MagicMock(size=100, mtime=1000.0)
    remote = RemoteFile("a", "vos:u/a", 100, 1000.0)
    assert _needs_upload(local, remote, False) is False


def test_needs_upload_size_differs():
    local = MagicMock(size=200, mtime=1000.0)
    remote = RemoteFile("a", "vos:u/a", 100, 1000.0)
    assert _needs_upload(local, remote, False) is True


def test_config_paths(tmp_path: Path):
    root = tmp_path / "src"
    root.mkdir()
    cfg = BackupConfig(
        job_name="j",
        vospace_root="vos:u/root",
        source_paths=[root],
        certfile=root / "cert.pem",
    )
    assert cfg.snapshots_uri == "vos:u/root/snapshots"
