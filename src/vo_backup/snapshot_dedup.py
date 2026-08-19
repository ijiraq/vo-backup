"""Compare files and plan snapshot deduplication via move + link."""

from __future__ import annotations

from vo_backup.md5_util import file_md5
from vo_backup.paths import LocalFile
from vo_backup.vospace import RemoteFile


def local_matches_remote(local: LocalFile, remote: RemoteFile | None) -> bool:
    """True if local file content matches remote metadata (MD5)."""
    if remote is None:
        return False
    try:
        local_digest = file_md5(local.abs_path)
    except OSError:
        return False
    if remote.md5 and local_digest == remote.md5.lower():
        return True
    return False


def unchanged_for_snapshot(
    local: LocalFile,
    prev: RemoteFile | None,
    current: RemoteFile | None,
) -> bool:
    """True if local content matches the previous snapshot entry."""
    if prev is None:
        return False
    if local_matches_remote(local, prev):
        return True
    if current and local_matches_remote(local, current):
        return True
    return False


def canonical_data_uri(prev: RemoteFile) -> str:
    if prev.is_link and prev.link_target:
        return prev.link_target
    return prev.uri
