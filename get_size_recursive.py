#!/usr/bin/env python3
"""Measure unique file count and size of a VOSpace tree.

Child LinkNodes are not followed (avoids double-counting snapshot/current
links). A start URI that is itself a link is resolved once. Listings run
concurrently on a thread pool because vos.Client is synchronous HTTP.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from vos import Client

DEFAULT_CERTFILE = Path.home() / ".ssl" / "cadcproxy.pem"
DEFAULT_WORKERS = 10

_thread_local = threading.local()

FetchNode = Callable[[str], Any]


@dataclass(frozen=True)
class WalkResult:
    size: int = 0
    files: int = 0
    skipped_links: int = 0

    def __add__(self, other: WalkResult) -> WalkResult:
        return WalkResult(
            size=self.size + other.size,
            files=self.files + other.files,
            skipped_links=self.skipped_links + other.skipped_links,
        )


def resolve_certfile(certfile: str | Path | None = None) -> Path:
    if certfile is not None:
        return Path(certfile).expanduser()
    env = os.environ.get("VOSPACE_CERTFILE")
    if env:
        return Path(env).expanduser()
    return DEFAULT_CERTFILE


def get_thread_client(certfile: str) -> Client:
    cached_cert = getattr(_thread_local, "certfile", None)
    client = getattr(_thread_local, "client", None)
    if client is None or cached_cert != certfile:
        client = Client(vospace_certfile=certfile)
        _thread_local.client = client
        _thread_local.certfile = certfile
    return client


def make_fetch_node(certfile: str) -> FetchNode:
    def fetch_node(uri: str) -> Any:
        client = get_thread_client(certfile)
        return client.get_node(uri, limit=None, force=True)

    return fetch_node


def _node_size(node: Any) -> int:
    return int(node.get_info()["size"])


def _children(node: Any) -> list[Any]:
    children = getattr(node, "node_list", None)
    if children is None:
        return []
    return list(children)


def classify_children(children: list[Any], verbose: bool = False) -> tuple[list[str], WalkResult]:
    """Split children into container URIs vs local file/skipped-link totals."""
    dirs: list[str] = []
    size = 0
    files = 0
    skipped = 0
    for child in children:
        if child.islink():
            skipped += 1
            continue
        if child.isdir():
            dirs.append(child.uri)
            continue
        nbytes = _node_size(child)
        files += 1
        size += nbytes
        if verbose:
            print(f"file: {child.uri} -- {nbytes:18d}")
    return dirs, WalkResult(size=size, files=files, skipped_links=skipped)


async def _fetch(
    uri: str,
    fetch_node: FetchNode,
    semaphore: asyncio.Semaphore,
    executor: ThreadPoolExecutor,
) -> Any:
    loop = asyncio.get_running_loop()
    async with semaphore:
        return await loop.run_in_executor(executor, fetch_node, uri)


async def _walk_container(
    node: Any,
    fetch_node: FetchNode,
    semaphore: asyncio.Semaphore,
    executor: ThreadPoolExecutor,
    verbose: bool,
) -> WalkResult:
    dirs, local = classify_children(_children(node), verbose=verbose)
    if not dirs:
        return local

    async def walk_dir(dir_uri: str) -> WalkResult:
        child = await _fetch(dir_uri, fetch_node, semaphore, executor)
        if child.islink():
            return WalkResult(skipped_links=1)
        if not child.isdir():
            nbytes = _node_size(child)
            if verbose:
                print(f"file: {child.uri} -- {nbytes:18d}")
            return WalkResult(size=nbytes, files=1)
        return await _walk_container(child, fetch_node, semaphore, executor, verbose)

    results = await asyncio.gather(*(walk_dir(uri) for uri in dirs))
    total = local
    for result in results:
        total = total + result
    return total


async def _walk_tree(
    uri: str,
    fetch_node: FetchNode,
    workers: int,
    verbose: bool,
) -> WalkResult:
    with ThreadPoolExecutor(max_workers=workers) as executor:
        semaphore = asyncio.Semaphore(workers)
        node = await _fetch(uri, fetch_node, semaphore, executor)
        if node.islink():
            target = getattr(node, "target", None)
            if not target:
                return WalkResult(skipped_links=1)
            node = await _fetch(target, fetch_node, semaphore, executor)
            if node.islink():
                return WalkResult(skipped_links=1)
        if not node.isdir():
            nbytes = _node_size(node)
            if verbose:
                print(f"file: {node.uri} -- {nbytes:18d}")
            return WalkResult(size=nbytes, files=1)
        return await _walk_container(node, fetch_node, semaphore, executor, verbose)


def walk_size(
    uri: str,
    *,
    certfile: str | Path | None = None,
    workers: int = DEFAULT_WORKERS,
    verbose: bool = False,
    fetch_node: FetchNode | None = None,
) -> WalkResult:
    if workers < 1:
        raise ValueError("workers must be at least 1")
    if fetch_node is None:
        fetch_node = make_fetch_node(str(resolve_certfile(certfile)))
    return asyncio.run(_walk_tree(uri, fetch_node, workers, verbose))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure unique file count and size of a VOSpace tree. "
            "Child LinkNodes are not followed."
        )
    )
    parser.add_argument("uri", help="VOSpace URI to walk, e.g. vos:user/backup")
    parser.add_argument(
        "--cert",
        default=None,
        help="X509 cert PEM (default: $VOSPACE_CERTFILE or ~/.ssl/cadcproxy.pem)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Concurrent listing threads (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print each data file as it is counted",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cert = resolve_certfile(args.cert)
    if not cert.is_file():
        print(f"VOSpace certificate not found: {cert}", file=sys.stderr)
        return 1
    result = walk_size(
        args.uri,
        certfile=cert,
        workers=args.workers,
        verbose=args.verbose,
    )
    print(f"size={result.size} files={result.files} skipped_links={result.skipped_links}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
