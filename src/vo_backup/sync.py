"""Incremental sync from local filesystem to VOSpace current/ mirror."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from vo_backup.config import BackupConfig
from vo_backup.paths import LocalFile, iter_local_files
from vo_backup.snapshot_dedup import local_matches_remote
from vo_backup.snapshots_layout import (
    latest_file_uri,
    latest_snapshot_index,
    targets_latest_area,
)
from vo_backup.state import RunStats
from vo_backup.vospace import RemoteFile, VOSpace

logger = logging.getLogger(__name__)

PROGRESS_INTERVAL = 50


def _needs_upload(
    local: LocalFile,
    remote: RemoteFile | None,
    verify_checksum: bool,
) -> bool:
    """Whether a data node in current/ should be replaced from disk."""
    if remote is None or remote.is_link:
        return True
    if local.size != remote.size:
        return True
    if local.mtime > remote.mtime + 1:
        return True
    if verify_checksum:
        return local.checksum() != (remote.md5 or "")
    return False


def _sync_one_file(
    vos: VOSpace,
    config: BackupConfig,
    local: LocalFile,
    current: RemoteFile | None,
    snap: RemoteFile | None,
    dry_run: bool,
    verify_checksum: bool,
) -> tuple[str, int]:
    """
    Sync a single file. Returns (action, bytes) where action is
    skipped, linked, uploaded, or error.
    """
    current_uri = vos.remote_uri(config.current_uri, local.rel_path)
    latest_target = latest_file_uri(config, local.rel_path)

    if current is None and snap and local_matches_remote(local, snap):
        try:
            parent = current_uri.rsplit("/", 1)[0]
            if parent and parent != current_uri:
                vos.mkdir_p(parent, dry_run=dry_run)
            vos.link(latest_target, current_uri, dry_run=dry_run)
            logger.info("Linked current/%s -> snapshots/latest/", local.rel_path)
            return ("linked", 0)
        except Exception as exc:
            logger.error("Failed to link %s: %s", local.rel_path, exc)
            return ("error", 0)

    if current and current.is_link:
        target = current.link_target
        if target and not targets_latest_area(config, vos.fix_uri(target)):
            snap_match = snap and local_matches_remote(local, snap)
            if snap_match:
                try:
                    vos.delete(current.uri, dry_run=dry_run)
                    parent = current_uri.rsplit("/", 1)[0]
                    if parent and parent != current_uri:
                        vos.mkdir_p(parent, dry_run=dry_run)
                    vos.link(latest_target, current_uri, dry_run=dry_run)
                    logger.info("Rewired stale link for current/%s", local.rel_path)
                    return ("linked", 0)
                except Exception as exc:
                    logger.error("Failed to rewire %s: %s", local.rel_path, exc)
                    return ("error", 0)

        from vo_backup.snapshot_dedup import canonical_data_uri

        target_info = vos.get_node_info(canonical_data_uri(current))
        if target_info and local_matches_remote(local, target_info):
            return ("skipped", 0)
        try:
            vos.delete(current.uri, dry_run=dry_run)
            vos.copy_local(str(local.abs_path), current_uri, dry_run=dry_run)
            logger.info(
                "Replaced link in current/%s (snapshot data unchanged)",
                local.rel_path,
            )
            return ("uploaded", local.size)
        except Exception as exc:
            logger.error("Failed to replace link for %s: %s", local.rel_path, exc)
            return ("error", 0)

    if not _needs_upload(local, current, verify_checksum):
        return ("skipped", 0)

    try:
        if current is not None:
            vos.delete(current.uri, dry_run=dry_run)
        vos.copy_local(str(local.abs_path), current_uri, dry_run=dry_run)
        return ("uploaded", local.size)
    except Exception as exc:
        logger.error("Failed to upload %s: %s", local.rel_path, exc)
        return ("error", 0)


def run_sync(config: BackupConfig, vos: VOSpace, dry_run: bool = False) -> RunStats:
    stats = RunStats()
    logger.info("Scanning local files...")
    local_files = iter_local_files(
        config.source_paths,
        config.include,
        config.exclude,
        verify_checksum=config.verify_checksum,
    )
    local_index = {f.rel_path: f for f in local_files}
    logger.info("Found %d local files", len(local_index))

    vos.mkdir_p(config.vospace_root, dry_run=dry_run)
    vos.mkdir_p(config.current_uri, dry_run=dry_run)

    logger.info("Listing remote current/ mirror...")
    current_index = vos.list_tree(config.current_uri)
    logger.info("Found %d remote files under current/", len(current_index))

    latest_id, snap_index = latest_snapshot_index(vos, config)
    if latest_id:
        logger.info(
            "Using snapshots/latest -> %s (%d paths)",
            latest_id,
            len(snap_index),
        )

    work = [
        (local, current_index.get(rel), snap_index.get(rel))
        for rel, local in local_index.items()
    ]

    def _run(item):
        local, current, snap = item
        return _sync_one_file(
            vos,
            config,
            local,
            current,
            snap,
            dry_run,
            config.verify_checksum,
        )

    if work:
        with ThreadPoolExecutor(max_workers=config.nstreams) as pool:
            futures = {pool.submit(_run, item): item[0] for item in work}
            done = 0
            for future in as_completed(futures):
                action, nbytes = future.result()
                done += 1
                if action == "uploaded":
                    stats.uploaded += 1
                    stats.bytes_uploaded += nbytes
                elif action == "linked":
                    stats.linked += 1
                elif action == "skipped":
                    stats.skipped += 1
                else:
                    stats.errors += 1
                if done % PROGRESS_INTERVAL == 0:
                    logger.info("Progress: %d/%d files", done, len(work))

    remote_only = set(current_index) - set(local_index)
    for rel in sorted(remote_only):
        remote_uri = current_index[rel].uri
        try:
            vos.delete(remote_uri, dry_run=dry_run)
            stats.deleted += 1
            logger.info("Deleted remote: %s", rel)
        except Exception as exc:
            logger.error("Failed to delete %s: %s", rel, exc)
            stats.errors += 1

    logger.info(
        "Sync complete: uploaded=%d linked=%d skipped=%d deleted=%d errors=%d bytes=%d",
        stats.uploaded,
        stats.linked,
        stats.skipped,
        stats.deleted,
        stats.errors,
        stats.bytes_uploaded,
    )
    return stats
