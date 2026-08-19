"""Snapshot manifest helpers."""

from __future__ import annotations

import json
import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

MANIFEST_NAME = ".vo-backup-manifest.json"


@dataclass
class SnapshotManifest:
    snapshot_id: str
    created_at: str
    hostname: str
    job_name: str
    file_count: int
    source_paths: list[str]
    uploaded: int = 0
    relocated: int = 0
    previous_snapshot_id: str | None = None

    @classmethod
    def create(
        cls,
        snapshot_id: str,
        job_name: str,
        source_paths: list[str],
        file_count: int,
        *,
        uploaded: int = 0,
        relocated: int = 0,
        previous_snapshot_id: str | None = None,
    ) -> SnapshotManifest:
        return cls(
            snapshot_id=snapshot_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            hostname=socket.gethostname(),
            job_name=job_name,
            file_count=file_count,
            source_paths=source_paths,
            uploaded=uploaded,
            relocated=relocated,
            previous_snapshot_id=previous_snapshot_id,
        )

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> SnapshotManifest:
        data: dict[str, Any] = json.loads(text)
        return cls(
            snapshot_id=data["snapshot_id"],
            created_at=data["created_at"],
            hostname=data.get("hostname", ""),
            job_name=data.get("job_name", ""),
            file_count=int(data.get("file_count", 0)),
            source_paths=list(data.get("source_paths", [])),
            uploaded=int(data.get("uploaded", 0)),
            relocated=int(data.get("relocated", 0)),
            previous_snapshot_id=data.get("previous_snapshot_id"),
        )
