"""Create point-in-time snapshots on VOSpace with link-based deduplication."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from vo_backup.config import BackupConfig, join_uri
from vo_backup.manifest import MANIFEST_NAME, SnapshotManifest
from vo_backup.paths import iter_local_files
from vo_backup.retention import list_snapshot_ids
from vo_backup.snapshot_dedup import canonical_data_uri, unchanged_for_snapshot
from vo_backup.snapshots_layout import (
    ensure_current_links_to_latest,
    set_latest_pointer,
)
from vo_backup.state import RunStats, utc_now_iso
from vo_backup.sync import run_sync
from vo_backup.vospace import VOSpace

logger = logging.getLogger(__name__)


def snapshot_id_now() -> str:
    return utc_now_iso()


def run_snapshot(
    config: BackupConfig,
    vos: VOSpace,
    dry_run: bool = False,
    skip_sync: bool = False,
) -> tuple[str, RunStats]:
    """
    Sync to current/, populate a new timestamped snapshot, point snapshots/latest
    at it, and rewire current/ so every file is a link into snapshots/latest/.
    """
    sync_stats = RunStats()
    if not skip_sync:
        sync_stats = run_sync(config, vos, dry_run=dry_run)

    existing_ids = list_snapshot_ids(vos, config)
    prev_id = existing_ids[-1] if existing_ids else None

    snap_id = snapshot_id_now()
    snap_root = join_uri(config.snapshots_uri, snap_id)
    vos.mkdir_p(config.snapshots_uri, dry_run=dry_run)
    vos.mkdir_p(snap_root, dry_run=dry_run)

    prev_index: dict = {}
    if prev_id:
        prev_root = join_uri(config.snapshots_uri, prev_id)
        logger.info("Loading previous snapshot %s for deduplication", prev_id)
        prev_index = vos.list_tree(prev_root)

    current_index = vos.list_tree(config.current_uri)

    local_files = iter_local_files(
        config.source_paths,
        config.include,
        config.exclude,
    )
    logger.info(
        "Creating snapshot %s (%d files, previous=%s)",
        snap_id,
        len(local_files),
        prev_id or "none",
    )

    upload_stats = RunStats()
    to_upload = []
    to_relocate = []
    to_move_from_current = []

    for local in local_files:
        prev = prev_index.get(local.rel_path)
        current = current_index.get(local.rel_path)
        if prev_id and unchanged_for_snapshot(local, prev, current):
            to_relocate.append((local, prev))
        elif current is not None and not current.is_link:
            to_move_from_current.append((local, current))
        else:
            to_upload.append(local)

    logger.info(
        "%d relocate from previous snapshot, %d move from current, %d upload",
        len(to_relocate),
        len(to_move_from_current),
        len(to_upload),
    )

    for local, prev in to_relocate:
        new_uri = vos.remote_uri(snap_root, local.rel_path)
        back_uri = prev.uri
        data_uri = canonical_data_uri(prev)
        try:
            if prev.is_link:
                vos.promote_link_unchanged(
                    data_uri, new_uri, back_uri, dry_run=dry_run
                )
            else:
                vos.promote_unchanged(
                    data_uri, new_uri, back_uri, dry_run=dry_run
                )
            upload_stats.relocated += 1
        except Exception as exc:
            logger.error(
                "Relocate failed for %s, will upload: %s",
                local.rel_path,
                exc,
            )
            to_upload.append(local)

    for local, current in to_move_from_current:
        new_uri = vos.remote_uri(snap_root, local.rel_path)
        try:
            vos.move(current.uri, new_uri, dry_run=dry_run)
            upload_stats.relocated += 1
            logger.debug("Moved current/%s into snapshot", local.rel_path)
        except Exception as exc:
            logger.error(
                "Move from current failed for %s, will upload: %s",
                local.rel_path,
                exc,
            )
            to_upload.append(local)

    def _upload(local):
        dest = vos.remote_uri(snap_root, local.rel_path)
        try:
            vos.copy_local(str(local.abs_path), dest, dry_run=dry_run)
            return ("ok", local.size)
        except Exception as exc:
            logger.error("Snapshot upload failed for %s: %s", local.rel_path, exc)
            return ("error", 0)

    if to_upload:
        with ThreadPoolExecutor(max_workers=config.nstreams) as pool:
            futures = [pool.submit(_upload, lf) for lf in to_upload]
            for future in as_completed(futures):
                status, nbytes = future.result()
                if status == "ok":
                    upload_stats.uploaded += 1
                    upload_stats.bytes_uploaded += nbytes
                else:
                    upload_stats.errors += 1

    set_latest_pointer(vos, config, snap_id, dry_run=dry_run)
    rewired = ensure_current_links_to_latest(
        vos, config, local_files, dry_run=dry_run
    )
    logger.info(
        "Pointed snapshots/latest at %s; %d current/ links updated",
        snap_id,
        rewired,
    )

    manifest = SnapshotManifest.create(
        snapshot_id=snap_id,
        job_name=config.job_name,
        source_paths=[str(p) for p in config.source_paths],
        file_count=len(local_files),
        uploaded=upload_stats.uploaded,
        relocated=upload_stats.relocated,
        previous_snapshot_id=prev_id,
    )
    manifest_uri = join_uri(snap_root, MANIFEST_NAME)
    vos.upload_text(manifest_uri, manifest.to_json(), dry_run=dry_run)

    combined = RunStats(
        uploaded=sync_stats.uploaded + upload_stats.uploaded,
        skipped=sync_stats.skipped,
        deleted=sync_stats.deleted,
        errors=sync_stats.errors + upload_stats.errors,
        bytes_uploaded=sync_stats.bytes_uploaded + upload_stats.bytes_uploaded,
        relocated=upload_stats.relocated,
        linked=sync_stats.linked + rewired,
    )
    logger.info(
        "Snapshot %s: %d files, %d relocated/moved, %d uploaded, %d errors",
        snap_id,
        len(local_files),
        upload_stats.relocated,
        upload_stats.uploaded,
        upload_stats.errors,
    )
    return snap_id, combined
