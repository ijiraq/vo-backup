"""Restore files from VOSpace current/ or snapshots/."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from vo_backup.config import BackupConfig, join_uri
from vo_backup.vospace import VOSpace

logger = logging.getLogger(__name__)


def resolve_restore_root(
    config: BackupConfig,
    source: str,
    snapshot_id: str | None,
) -> str:
    if source == "current":
        return config.current_uri
    if source == "snapshot":
        if not snapshot_id:
            raise ValueError("--snapshot-id is required when --from snapshot")
        return join_uri(config.snapshots_uri, snapshot_id)
    raise ValueError("--from must be 'current' or 'snapshot'")


def run_restore(
    config: BackupConfig,
    vos: VOSpace,
    *,
    source: str,
    snapshot_id: str | None,
    dest: Path,
    paths: list[str] | None = None,
    dry_run: bool = False,
) -> tuple[int, int]:
    root_uri = resolve_restore_root(config, source, snapshot_id)
    remote_index = vos.list_tree(root_uri)
    if not remote_index:
        logger.warning("No files found under %s", root_uri)

    dest = dest.expanduser().resolve()
    restored = 0
    errors = 0

    selected = sorted(remote_index)
    if paths:
        path_set = {p.strip("/") for p in paths}
        selected = [r for r in selected if any(r == p or r.startswith(p + "/") for p in path_set)]

    for rel in selected:
        remote_uri = vos.remote_uri(root_uri, rel)
        local_path = dest / rel
        try:
            if not dry_run:
                local_path.parent.mkdir(parents=True, exist_ok=True)
            vos.copy_remote_to_local(remote_uri, str(local_path), dry_run=dry_run)
            restored += 1
            if restored % 50 == 0:
                logger.info("Restored %d files...", restored)
        except Exception as exc:
            logger.error("Failed to restore %s: %s", rel, exc)
            errors += 1

    logger.info("Restore complete: restored=%d errors=%d -> %s", restored, errors, dest)
    return restored, errors
