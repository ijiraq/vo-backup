"""snapshots/latest pointer and current/ link layout."""

from __future__ import annotations

import os

from vo_backup.config import BackupConfig, join_uri
from vo_backup.paths import LocalFile
from vo_backup.vospace import VOSpace, RemoteFile

LATEST_NAME = "latest"


def latest_pointer_uri(config: BackupConfig) -> str:
    return join_uri(config.snapshots_uri, LATEST_NAME)


def latest_file_uri(config: BackupConfig, rel_path: str) -> str:
    return join_uri(config.snapshots_uri, LATEST_NAME, rel_path)


def targets_latest_area(config: BackupConfig, uri: str) -> bool:
    """True if uri is under snapshots/latest/ (the stable link prefix)."""
    prefix = join_uri(config.snapshots_uri, LATEST_NAME)
    uri = uri.rstrip("/")
    prefix = prefix.rstrip("/")
    return uri == prefix or uri.startswith(prefix + "/")


def resolve_latest_snapshot_id(vos: VOSpace, config: BackupConfig) -> str | None:
    info = vos.get_node_info(latest_pointer_uri(config))
    if info is None or not info.is_link or not info.link_target:
        return None
    return os.path.basename(info.link_target.rstrip("/"))


def latest_snapshot_index(
    vos: VOSpace, config: BackupConfig
) -> tuple[str | None, dict[str, RemoteFile]]:
    """List files under snapshots/latest/ (follows the latest pointer)."""
    ptr = latest_pointer_uri(config)
    if not vos.path_exists(ptr.rstrip("/")):
        return None, {}
    snap_id = resolve_latest_snapshot_id(vos, config)
    return snap_id, vos.list_tree(ptr + "/")


def set_latest_pointer(
    vos: VOSpace,
    config: BackupConfig,
    snap_id: str,
    *,
    dry_run: bool = False,
) -> None:
    """Point snapshots/latest at snapshots/{snap_id}/."""
    target = join_uri(config.snapshots_uri, snap_id)
    pointer = latest_pointer_uri(config)
    vos.mkdir_p(config.snapshots_uri, dry_run=dry_run)
    if vos.path_exists(pointer):
        vos.delete(pointer, dry_run=dry_run)
    vos.link(target, pointer, dry_run=dry_run)


def ensure_current_links_to_latest(
    vos: VOSpace,
    config: BackupConfig,
    local_files: list[LocalFile],
    *,
    dry_run: bool = False,
) -> int:
    """Make each current/ path a link to snapshots/latest/{rel}. Returns count rewired."""
    rewired = 0
    for local in local_files:
        current_uri = vos.remote_uri(config.current_uri, local.rel_path)
        target_uri = latest_file_uri(config, local.rel_path)
        info = vos.get_node_info(current_uri)
        if (
            info
            and info.is_link
            and info.link_target
            and targets_latest_area(config, vos.fix_uri(info.link_target))
        ):
            continue
        parent = current_uri.rsplit("/", 1)[0]
        if parent and parent != current_uri:
            vos.mkdir_p(parent, dry_run=dry_run)
        if info is not None:
            vos.delete(current_uri, dry_run=dry_run)
        vos.link(target_uri, current_uri, dry_run=dry_run)
        rewired += 1
    return rewired
