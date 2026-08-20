from pathlib import Path

import pytest
import yaml

from vo_backup.config import (
    DEFAULT_CERTFILE,
    create_config_interactively,
    join_uri,
    load_config,
    resolve_certfile,
    write_config,
)


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


def test_write_config_defaults(tmp_path: Path):
    src = tmp_path / "docs"
    src.mkdir()
    cfg_path = tmp_path / "config.yaml"

    write_config(
        cfg_path,
        job_name="docs",
        vospace_root="vos:user/backups/docs",
        source_paths=[src],
    )

    raw = yaml.safe_load(cfg_path.read_text())
    assert raw["job_name"] == "docs"
    assert raw["vospace_root"] == "vos:user/backups/docs"
    assert raw["source_paths"] == [str(src.resolve())]
    assert raw["retention_days"] == 90
    assert raw["exclude"] == [
        "**/.git/**",
        "**/__pycache__/**",
        "**/node_modules/**",
    ]
    cfg = load_config(cfg_path)
    assert cfg.source_paths == [src.resolve()]


def test_create_config_interactively(tmp_path: Path):
    src = tmp_path / "project"
    src.mkdir()
    cfg_path = tmp_path / "config.yaml"
    answers = iter(["project", "vos:user/backups/laptop"])
    messages: list[str] = []

    created = create_config_interactively(
        cfg_path,
        prompt=lambda _msg: next(answers),
        echo=messages.append,
        cwd=tmp_path,
    )

    assert created == cfg_path
    cfg = load_config(cfg_path)
    assert cfg.job_name == "project"
    assert cfg.vospace_root == "vos:user/backups/laptop"
    assert cfg.source_paths == [src.resolve()]
    assert messages == []


def test_create_config_interactively_retries_invalid_inputs(tmp_path: Path):
    src = tmp_path / "data"
    src.mkdir()
    cfg_path = tmp_path / "config.yaml"
    answers = iter(
        [
            "missing",
            "data",
            "not-a-vos-uri",
            "vos:user/backups/data",
        ]
    )
    messages: list[str] = []

    create_config_interactively(
        cfg_path,
        prompt=lambda _msg: next(answers),
        echo=messages.append,
        cwd=tmp_path,
    )

    assert any("does not exist" in msg for msg in messages)
    assert any("must start with 'vos:'" in msg for msg in messages)
    cfg = load_config(cfg_path)
    assert cfg.source_paths == [src.resolve()]
    assert cfg.vospace_root == "vos:user/backups/data"
