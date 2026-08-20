"""Load and validate backup job configuration."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

WEEKDAYS = frozenset(
    {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
)

DEFAULT_CERTFILE = Path.home() / ".ssl" / "cadcproxy.pem"
DEFAULT_CONFIG_PATH = Path("vo_backup_config.yaml")

DEFAULT_INCLUDE = ["**/*"]
DEFAULT_EXCLUDE = [
    "**/.git/**",
    "**/__pycache__/**",
    "**/node_modules/**",
]


def resolve_certfile(certfile: Path | None = None) -> Path:
    """Return the X509 certificate path for VOSpace (default: ~/.ssl/cadcproxy.pem)."""
    if certfile is not None:
        return certfile.expanduser()
    env = os.environ.get("VOSPACE_CERTFILE")
    if env:
        return Path(env).expanduser()
    return DEFAULT_CERTFILE


@dataclass
class BackupConfig:
    job_name: str
    vospace_root: str
    source_paths: list[Path]
    certfile: Path
    include: list[str] = field(default_factory=lambda: ["**/*"])
    exclude: list[str] = field(default_factory=list)
    retention_days: int = 90
    snapshot_weekday: str = "sunday"
    nstreams: int = 4
    verify_checksum: bool = False
    state_file: Path | None = None

    @property
    def current_uri(self) -> str:
        return join_uri(self.vospace_root, "current")

    @property
    def snapshots_uri(self) -> str:
        return join_uri(self.vospace_root, "snapshots")


def join_uri(base: str, *parts: str) -> str:
    base = base.rstrip("/")
    suffix = "/".join(p.strip("/") for p in parts if p)
    if "://" in base:
        scheme, rest = base.split("://", 1)
        rest = rest.rstrip("/")
        if suffix:
            return f"{scheme}://{rest}/{suffix}"
        return f"{scheme}://{rest}"
    if suffix:
        return f"{base}/{suffix}"
    return base


def _sanitize_job_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-._")
    return cleaned or "backup"


def write_config(
    path: str | Path,
    *,
    job_name: str,
    vospace_root: str,
    source_paths: list[str | Path],
) -> None:
    """Write a vo_backup_config.yaml with required fields and sensible defaults."""
    path = Path(path)
    resolved_sources = [str(Path(p).expanduser().resolve()) for p in source_paths]
    payload = {
        "job_name": job_name,
        "vospace_root": vospace_root,
        "source_paths": resolved_sources,
        "include": list(DEFAULT_INCLUDE),
        "exclude": list(DEFAULT_EXCLUDE),
        "retention_days": 90,
        "snapshot_weekday": "sunday",
        "nstreams": 4,
        "verify_checksum": False,
    }
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, default_flow_style=False, sort_keys=False)


def create_config_interactively(
    path: str | Path,
    *,
    prompt: Callable[[str], str],
    echo: Callable[[str], None] | None = None,
    cwd: Path | None = None,
) -> Path:
    """
    Prompt for settings without good defaults and write a new config file.

    Asks for:
    - source directory relative to cwd
    - VOSpace root URI (vos:...)
    """
    path = Path(path)
    cwd = (cwd or Path.cwd()).resolve()
    echo = echo or (lambda _msg: None)

    while True:
        rel = prompt(
            "Directory to back up (relative to current directory)"
        ).strip()
        if not rel:
            echo("Please enter a directory path.")
            continue
        source = (cwd / Path(rel).expanduser()).resolve()
        if source.exists():
            break
        echo(f"Path does not exist: {source}")

    while True:
        vospace_root = prompt(
            "VOSpace destination (e.g. vos:username/backups/laptop)"
        ).strip()
        if not vospace_root:
            echo("Please enter a VOSpace URI.")
            continue
        if vospace_root.startswith("vos:"):
            break
        echo("VOSpace destination must start with 'vos:'")

    job_name = _sanitize_job_name(
        source.name if source.name not in ("", ".") else cwd.name
    )
    write_config(
        path,
        job_name=job_name,
        vospace_root=vospace_root,
        source_paths=[source],
    )
    return path


def load_config(path: str | Path) -> BackupConfig:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Config not found: {path}")

    with path.open(encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    required = ("job_name", "vospace_root", "source_paths")
    missing = [k for k in required if k not in raw or raw[k] in (None, "")]
    if missing:
        raise ValueError(f"Missing required config keys: {', '.join(missing)}")

    vospace_root = str(raw["vospace_root"]).strip()
    if not vospace_root.startswith("vos:"):
        raise ValueError("vospace_root must start with 'vos:'")

    source_paths = []
    for entry in raw["source_paths"]:
        p = Path(entry).expanduser().resolve()
        if not p.exists():
            raise ValueError(f"source_paths entry does not exist: {entry}")
        source_paths.append(p)

    snapshot_weekday = str(raw.get("snapshot_weekday", "sunday")).lower()
    if snapshot_weekday not in WEEKDAYS:
        raise ValueError(f"snapshot_weekday must be one of: {', '.join(sorted(WEEKDAYS))}")

    retention_days = int(raw.get("retention_days", 90))
    if retention_days < 1:
        raise ValueError("retention_days must be at least 1")

    nstreams = int(raw.get("nstreams", 4))
    if nstreams < 1:
        raise ValueError("nstreams must be at least 1")

    certfile = raw.get("certfile")
    if certfile:
        certfile = Path(str(certfile)).expanduser()
    else:
        certfile = resolve_certfile(None)

    state_file = raw.get("state_file")
    if state_file:
        state_file = Path(state_file).expanduser()
    else:
        cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        state_file = cache / "vo_backup" / f"{raw['job_name']}.json"

    return BackupConfig(
        job_name=str(raw["job_name"]),
        vospace_root=vospace_root,
        source_paths=source_paths,
        certfile=certfile,
        include=list(raw.get("include") or ["**/*"]),
        exclude=list(raw.get("exclude") or []),
        retention_days=retention_days,
        snapshot_weekday=snapshot_weekday,
        nstreams=nstreams,
        verify_checksum=bool(raw.get("verify_checksum", False)),
        state_file=state_file,
    )
