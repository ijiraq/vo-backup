"""Walk local trees with pathspec include/exclude rules."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

import pathspec


@dataclass(frozen=True)
class LocalFile:
    rel_path: str
    abs_path: Path
    size: int
    mtime: float

    def checksum(self) -> str:
        digest = hashlib.sha256()
        with self.abs_path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()


def build_matcher(include: list[str], exclude: list[str]) -> pathspec.PathSpec:
    patterns = list(include) + [f"!{p}" for p in exclude]
    return pathspec.PathSpec.from_lines("gitignore", patterns)


def source_prefix(source_root: Path) -> str:
    return source_root.name


def iter_local_files(
    source_paths: list[Path],
    include: list[str],
    exclude: list[str],
    verify_checksum: bool = False,
) -> list[LocalFile]:
    matcher = build_matcher(include, exclude)
    files: list[LocalFile] = []

    for source_root in source_paths:
        prefix = source_prefix(source_root)
        for dirpath, dirnames, filenames in os.walk(source_root, followlinks=False):
            dirpath_path = Path(dirpath)
            dirnames[:] = sorted(
                d for d in dirnames if _include_dir(source_root, prefix, dirpath_path / d, matcher)
            )
            for name in sorted(filenames):
                abs_path = dirpath_path / name
                if abs_path.is_symlink():
                    continue
                if not abs_path.is_file():
                    continue
                rel = abs_path.relative_to(source_root).as_posix()
                rel_path = f"{prefix}/{rel}" if rel else prefix
                if not matcher.match_file(rel_path):
                    continue
                stat = abs_path.stat()
                files.append(
                    LocalFile(
                        rel_path=rel_path,
                        abs_path=abs_path,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                    )
                )

    return files


def _include_dir(
    source_root: Path,
    prefix: str,
    path: Path,
    matcher: pathspec.PathSpec,
) -> bool:
    rel = path.relative_to(source_root).as_posix()
    rel_path = f"{prefix}/{rel}/" if rel else f"{prefix}/"
    return matcher.match_file(rel_path) or matcher.match_file(rel_path.rstrip("/"))
