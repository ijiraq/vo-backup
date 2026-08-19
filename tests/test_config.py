from pathlib import Path

import pytest

from vo_backup.config import DEFAULT_CERTFILE, join_uri, load_config, resolve_certfile


def test_join_uri():
    assert join_uri("vos:user/root", "current") == "vos:user/root/current"
    assert join_uri("vos:user/root/", "snapshots", "id") == "vos:user/root/snapshots/id"


def test_load_config(tmp_path: Path):
    src = tmp_path / "data"
    src.mkdir()
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
job_name: test-job
vospace_root: "vos:testuser/backups/test"
source_paths:
  - {src}
retention_days: 30
""".format(src=src)
    )
    cfg = load_config(cfg_path)
    assert cfg.job_name == "test-job"
    assert cfg.current_uri == "vos:testuser/backups/test/current"
    assert cfg.retention_days == 30


def test_resolve_certfile_default():
    assert resolve_certfile(None) == DEFAULT_CERTFILE


def test_resolve_certfile_override(tmp_path: Path):
    cert = tmp_path / "my.pem"
    cert.write_text("dummy")
    assert resolve_certfile(cert) == cert


def test_load_config_missing_key(tmp_path: Path):
    cfg_path = tmp_path / "bad.yaml"
    cfg_path.write_text("job_name: x\n")
    with pytest.raises(ValueError, match="Missing required"):
        load_config(cfg_path)
