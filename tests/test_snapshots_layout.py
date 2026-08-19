from pathlib import Path

from vo_backup.config import BackupConfig, join_uri
from vo_backup.snapshots_layout import (
    latest_file_uri,
    latest_pointer_uri,
    targets_latest_area,
)


def test_latest_uris(tmp_path: Path):
    src = tmp_path / "s"
    src.mkdir()
    cfg = BackupConfig(
        job_name="j",
        vospace_root="vos:u/backup",
        source_paths=[src],
        certfile=tmp_path / "c.pem",
    )
    assert latest_pointer_uri(cfg) == "vos:u/backup/snapshots/latest"
    assert latest_file_uri(cfg, "proj/a.txt") == (
        "vos:u/backup/snapshots/latest/proj/a.txt"
    )


def test_targets_latest_area(tmp_path: Path):
    src = tmp_path / "s"
    src.mkdir()
    cfg = BackupConfig(
        job_name="j",
        vospace_root="vos:u/backup",
        source_paths=[src],
        certfile=tmp_path / "c.pem",
    )
    assert targets_latest_area(cfg, latest_file_uri(cfg, "a"))
    assert not targets_latest_area(
        cfg, join_uri(cfg.snapshots_uri, "2026-01-01T120000Z", "a")
    )
