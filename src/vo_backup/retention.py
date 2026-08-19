"""Age-based pruning of old snapshots."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from vo_backup.config import BackupConfig, join_uri
from vo_backup.snapshots_layout import LATEST_NAME, resolve_latest_snapshot_id
from vo_backup.vospace import VOSpace

logger = logging.getLogger(__name__)

SNAPSHOT_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{6}Z$")


def parse_snapshot_id(snap_id: str) -> datetime | None:
    if not SNAPSHOT_ID_RE.match(snap_id):
        return None
    try:
        return datetime.strptime(snap_id, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def list_snapshot_ids(vos: VOSpace, config: BackupConfig) -> list[str]:
    names = vos.list_container_names(config.snapshots_uri)
    ids = []
    for name in names:
        name = name.rstrip("/")
        if parse_snapshot_id(name):
            ids.append(name)
    return sorted(ids)


def run_prune(config: BackupConfig, vos: VOSpace, dry_run: bool = False) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.retention_days)
    protected = resolve_latest_snapshot_id(vos, config)
    removed = 0
    for snap_id in list_snapshot_ids(vos, config):
        if snap_id == LATEST_NAME or snap_id == protected:
            continue
        created = parse_snapshot_id(snap_id)
        if created is None or created >= cutoff:
            continue
        uri = join_uri(config.snapshots_uri, snap_id)
        logger.info(
            "Pruning snapshot %s (older than %d days)",
            snap_id,
            config.retention_days,
        )
        vos.recursive_delete(uri, dry_run=dry_run)
        removed += 1
    logger.info("Pruned %d snapshot(s)", removed)
    return removed
