"""Local JSON state for last successful runs."""

from __future__ import annotations

import json
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


@dataclass
class RunStats:
    uploaded: int = 0
    skipped: int = 0
    deleted: int = 0
    errors: int = 0
    bytes_uploaded: int = 0
    relocated: int = 0
    linked: int = 0


@dataclass
class JobState:
    job_name: str
    hostname: str = field(default_factory=socket.gethostname)
    last_sync_at: str | None = None
    last_snapshot_at: str | None = None
    last_sync_stats: dict[str, Any] | None = None
    last_snapshot_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobState:
        return cls(
            job_name=data.get("job_name", ""),
            hostname=data.get("hostname", socket.gethostname()),
            last_sync_at=data.get("last_sync_at"),
            last_snapshot_at=data.get("last_snapshot_at"),
            last_sync_stats=data.get("last_sync_stats"),
            last_snapshot_id=data.get("last_snapshot_id"),
        )


def load_state(path: Path, job_name: str) -> JobState:
    if not path.exists():
        return JobState(job_name=job_name)
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    state = JobState.from_dict(data)
    state.job_name = job_name
    return state


def save_state(path: Path, state: JobState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(state.to_dict(), fh, indent=2)
        fh.write("\n")
