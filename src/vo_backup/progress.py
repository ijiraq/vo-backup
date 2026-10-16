"""Estimate backup progress by comparing local sources to VOSpace current/."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cadcutils import exceptions as cadc_exceptions

from vo_backup.config import BackupConfig, join_uri
from vo_backup.paths import iter_local_files
from vo_backup.vospace import VOSpace

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProgressReport:
    local_files: int
    local_bytes: int
    remote_files: int
    done_files: int
    done_bytes: int
    remaining_files: int
    remaining_bytes: int

    @property
    def file_pct(self) -> float:
        if self.local_files == 0:
            return 100.0
        return 100.0 * self.done_files / self.local_files

    @property
    def byte_pct(self) -> float:
        if self.local_bytes == 0:
            return 100.0
        return 100.0 * self.done_bytes / self.local_bytes


@dataclass(frozen=True)
class SamplePoint:
    ts: float
    done_bytes: int
    done_files: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "done_bytes": self.done_bytes,
            "done_files": self.done_files,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SamplePoint:
        return cls(
            ts=float(data["ts"]),
            done_bytes=int(data["done_bytes"]),
            done_files=int(data["done_files"]),
        )


def list_remote_sizes(vos: VOSpace, root_uri: str) -> dict[str, int]:
    """
    Walk a VOSpace tree and return rel_path -> size.

    Unlike VOSpace.list_tree, this does not follow LinkNode targets (no
    extra get_node_info round-trips), which keeps progress checks fast.
    """
    root_uri = vos.fix_uri(root_uri.rstrip("/") + "/")
    result: dict[str, int] = {}
    _walk_sizes(vos, root_uri, "", result)
    return result


def _walk_sizes(
    vos: VOSpace, uri: str, prefix: str, result: dict[str, int]
) -> None:
    try:
        children = vos.client.get_children_info(uri, force=True)
    except cadc_exceptions.NotFoundException:
        return

    for child in children:
        name = child.name.rstrip("/")
        rel = f"{prefix}/{name}".lstrip("/") if prefix else name
        if child.type == "vos:ContainerNode":
            child_uri = join_uri(uri.rstrip("/"), name)
            _walk_sizes(vos, child_uri + "/", rel, result)
        elif child.type in ("vos:DataNode", "vos:LinkNode"):
            child.setattr()
            size = int(child.attr.get("st_size", 0))
            result[rel] = size


def compute_progress(
    local_sizes: dict[str, int], remote_paths: set[str] | dict[str, int]
) -> ProgressReport:
    """
    Compare local path->size map to remote path set (or path->size map).

    Done/remaining bytes use local sizes so remaining matches bytes still
    to upload from disk.
    """
    remote_set = set(remote_paths)
    local_files = len(local_sizes)
    local_bytes = sum(local_sizes.values())
    done_files = 0
    done_bytes = 0
    remaining_files = 0
    remaining_bytes = 0

    for path, size in local_sizes.items():
        if path in remote_set:
            done_files += 1
            done_bytes += size
        else:
            remaining_files += 1
            remaining_bytes += size

    return ProgressReport(
        local_files=local_files,
        local_bytes=local_bytes,
        remote_files=len(remote_set),
        done_files=done_files,
        done_bytes=done_bytes,
        remaining_files=remaining_files,
        remaining_bytes=remaining_bytes,
    )


def collect_local_sizes(config: BackupConfig) -> dict[str, int]:
    files = iter_local_files(config.source_paths, config.include, config.exclude)
    return {f.rel_path: f.size for f in files}


def estimate_progress(config: BackupConfig, vos: VOSpace) -> ProgressReport:
    logger.info("Scanning local files...")
    local_sizes = collect_local_sizes(config)
    logger.info("Found %d local files (%s)", len(local_sizes), format_bytes(sum(local_sizes.values())))

    logger.info("Listing remote current/ (light walk)...")
    remote_sizes = list_remote_sizes(vos, config.current_uri)
    logger.info("Found %d remote nodes under current/", len(remote_sizes))

    return compute_progress(local_sizes, remote_sizes)


def parse_started(value: str, *, now: datetime | None = None) -> datetime:
    """Parse --started as YYYY-MM-DD or an ISO-8601 timestamp (Z or offset)."""
    value = value.strip()
    now = now or datetime.now(timezone.utc)

    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt

    normalized = value.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(
            f"Invalid --started value {value!r}; use YYYY-MM-DD or ISO-8601"
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def eta_seconds_from_started(
    started: datetime,
    done_bytes: int,
    remaining_bytes: int,
    *,
    now: datetime | None = None,
) -> float | None:
    now = now or datetime.now(timezone.utc)
    elapsed = (now - started).total_seconds()
    if elapsed <= 0 or done_bytes <= 0:
        return None
    rate = done_bytes / elapsed
    if rate <= 0:
        return None
    return remaining_bytes / rate


def eta_seconds_from_samples(
    previous: SamplePoint,
    current: SamplePoint,
    remaining_bytes: int,
) -> float | None:
    elapsed = current.ts - previous.ts
    gained = current.done_bytes - previous.done_bytes
    if elapsed <= 0 or gained <= 0:
        return None
    rate = gained / elapsed
    if rate <= 0:
        return None
    return remaining_bytes / rate


def load_sample(path: Path) -> SamplePoint | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return SamplePoint.from_dict(data)


def save_sample(path: Path, sample: SamplePoint) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(sample.to_dict(), fh, indent=2)
        fh.write("\n")


def format_bytes(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    value = float(n)
    for unit in units:
        if abs(value) < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{n} B"


def format_duration(seconds: float) -> str:
    if seconds < 0:
        seconds = 0
    secs = int(round(seconds))
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, rem = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{rem}s")
    if days:
        return " ".join(parts[:2])
    if hours:
        return " ".join(parts[:3])
    return " ".join(parts)


def format_report(
    report: ProgressReport,
    *,
    eta_seconds: float | None = None,
    eta_source: str | None = None,
) -> str:
    lines = [
        f"Local:  {report.local_files:,} files  {format_bytes(report.local_bytes)}",
        f"Remote: {report.remote_files:,} files present in current/",
        (
            f"Done:   {report.done_files:,} files ({report.file_pct:.0f}%)  "
            f"{format_bytes(report.done_bytes)} ({report.byte_pct:.0f}%)"
        ),
        (
            f"Left:   {report.remaining_files:,} files  "
            f"{format_bytes(report.remaining_bytes)}"
        ),
    ]
    if eta_seconds is not None and eta_source:
        lines.append(f"ETA:    ~{format_duration(eta_seconds)} ({eta_source})")
    elif eta_source:
        lines.append(f"ETA:    unavailable ({eta_source})")
    return "\n".join(lines)
