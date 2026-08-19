"""Thin wrapper around vos.Client for backup operations."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import vos
from cadcutils import exceptions as cadc_exceptions

from vo_backup.config import DEFAULT_CERTFILE, join_uri, resolve_certfile

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteFile:
    rel_path: str
    uri: str
    size: int
    mtime: float
    md5: str | None = None
    is_link: bool = False
    link_target: str | None = None


_thread_local = threading.local()


def create_client(certfile: Path | None = None) -> vos.Client:
    """Create a vos.Client authenticated with an X509 proxy certificate."""
    path = resolve_certfile(certfile)
    if not path.is_file():
        raise FileNotFoundError(
            f"VOSpace certificate not found: {path}\n"
            "Obtain one with: cadc-get-cert -u <username> -f "
            f"{DEFAULT_CERTFILE}"
        )
    logger.debug("Authenticating with certificate %s", path)
    return vos.Client(vospace_certfile=str(path))


def get_thread_client(certfile: Path | None) -> vos.Client:
    key = str(resolve_certfile(certfile))
    clients = getattr(_thread_local, "clients", None)
    if clients is None:
        clients = {}
        _thread_local.clients = clients
    if key not in clients:
        clients[key] = create_client(certfile)
    return clients[key]


class VOSpace:
    def __init__(self, certfile: Path | None = None, nstreams: int = 4):
        self.certfile = resolve_certfile(certfile)
        self.nstreams = nstreams
        self._client = create_client(self.certfile)

    @property
    def client(self) -> vos.Client:
        return self._client

    def thread_client(self) -> vos.Client:
        return get_thread_client(self.certfile)

    def fix_uri(self, uri: str) -> str:
        return self._client.fix_uri(uri)

    def path_exists(self, uri: str) -> bool:
        uri = self.fix_uri(uri)
        try:
            return bool(self._client.access(uri))
        except Exception:
            return self._client.isdir(uri)

    def _path_exists(self, uri: str) -> bool:
        return self.path_exists(uri)

    def mkdir(self, uri: str, dry_run: bool = False) -> None:
        uri = self.fix_uri(uri)
        if dry_run:
            logger.info("[dry-run] mkdir %s", uri)
            return
        try:
            self._client.mkdir(uri)
        except (cadc_exceptions.AlreadyExistsException, OSError):
            pass

    def mkdir_p(self, uri: str, dry_run: bool = False) -> None:
        """Create a container and all missing parent containers (like vmkdir -p)."""
        uri = self.fix_uri(uri).rstrip("/")
        if dry_run:
            logger.info("[dry-run] mkdir -p %s", uri)
            return
        if self._path_exists(uri):
            return

        pending: list[str] = []
        current = uri
        while current and not self._path_exists(current):
            pending.append(os.path.basename(current))
            parent = os.path.dirname(current)
            if not parent or parent == current:
                break
            current = parent

        build = current
        while pending:
            part = pending.pop()
            build = os.path.join(build, part) if build else part
            self.mkdir(build)

    def delete(self, uri: str, dry_run: bool = False) -> None:
        uri = self.fix_uri(uri)
        if dry_run:
            logger.info("[dry-run] delete %s", uri)
            return
        try:
            self._client.delete(uri)
        except cadc_exceptions.NotFoundException:
            pass

    def move(self, src_uri: str, dest_uri: str, dry_run: bool = False) -> None:
        src_uri = self.fix_uri(src_uri)
        dest_uri = self.fix_uri(dest_uri)
        if dry_run:
            logger.info("[dry-run] move %s -> %s", src_uri, dest_uri)
            return
        parent = dest_uri.rsplit("/", 1)[0]
        if parent and parent != dest_uri:
            self.mkdir_p(parent)
        # vos.Client.move() returns False on success; failures raise OSError.
        self._client.move(src_uri, dest_uri)

    def link(self, target_uri: str, link_uri: str, dry_run: bool = False) -> None:
        """Create link_uri as a LinkNode pointing at target_uri (vln semantics)."""
        if dry_run:
            logger.info("[dry-run] link %s -> %s", target_uri, link_uri)
            return
        self._client.link(target_uri, link_uri)

    def promote_unchanged(
        self,
        data_uri: str,
        new_uri: str,
        back_link_uri: str,
        *,
        dry_run: bool = False,
    ) -> None:
        """Move data to the new snapshot path; leave a link at the old path."""
        data_uri = self.fix_uri(data_uri)
        new_uri = self.fix_uri(new_uri)
        back_link_uri = self.fix_uri(back_link_uri)
        if data_uri == new_uri:
            self.link(new_uri, back_link_uri, dry_run=dry_run)
            return
        self.move(data_uri, new_uri, dry_run=dry_run)
        self.link(new_uri, back_link_uri, dry_run=dry_run)

    def promote_link_unchanged(
        self,
        canonical_uri: str,
        new_uri: str,
        back_link_uri: str,
        *,
        dry_run: bool = False,
    ) -> None:
        """Point new snapshot path at existing data; old path becomes link to new."""
        canonical_uri = self.fix_uri(canonical_uri)
        new_uri = self.fix_uri(new_uri)
        back_link_uri = self.fix_uri(back_link_uri)
        self.mkdir_p(new_uri.rsplit("/", 1)[0])
        self.link(canonical_uri, new_uri, dry_run=dry_run)
        if back_link_uri != new_uri:
            self.delete(back_link_uri, dry_run=dry_run)
            self.link(new_uri, back_link_uri, dry_run=dry_run)

    def recursive_delete(self, uri: str, dry_run: bool = False) -> None:
        uri = self.fix_uri(uri)
        if dry_run:
            logger.info("[dry-run] recursive_delete %s", uri)
            return
        try:
            self._client.recursive_delete(uri)
        except cadc_exceptions.NotFoundException:
            pass

    def copy_local(self, local_path: str, remote_uri: str, dry_run: bool = False) -> None:
        remote_uri = self.fix_uri(remote_uri)
        if dry_run:
            logger.info("[dry-run] copy %s -> %s", local_path, remote_uri)
            return
        parent = remote_uri.rsplit("/", 1)[0]
        if parent and parent != remote_uri:
            self.mkdir_p(parent)
        client = self.thread_client()
        client.copy(local_path, remote_uri)

    def copy_remote_to_local(
        self, remote_uri: str, local_path: str, dry_run: bool = False
    ) -> None:
        remote_uri = self.fix_uri(remote_uri)
        if dry_run:
            logger.info("[dry-run] copy %s -> %s", remote_uri, local_path)
            return
        os.makedirs(os.path.dirname(local_path) or ".", exist_ok=True)
        self._client.copy(remote_uri, local_path)

    def upload_text(self, remote_uri: str, content: str, dry_run: bool = False) -> None:
        remote_uri = self.fix_uri(remote_uri)
        if dry_run:
            logger.info("[dry-run] upload text to %s", remote_uri)
            return
        import tempfile as tf

        with tf.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fh:
            fh.write(content)
            tmp = fh.name
        try:
            self.copy_local(tmp, remote_uri)
        finally:
            os.unlink(tmp)

    def list_tree(self, root_uri: str) -> dict[str, RemoteFile]:
        root_uri = self.fix_uri(root_uri.rstrip("/") + "/")
        result: dict[str, RemoteFile] = {}
        self._walk_remote(root_uri, "", result)
        return result

    def _walk_remote(
        self, uri: str, prefix: str, result: dict[str, RemoteFile]
    ) -> None:
        try:
            children = self._client.get_children_info(uri, force=True)
        except cadc_exceptions.NotFoundException:
            return

        for child in children:
            name = child.name.rstrip("/")
            rel = f"{prefix}/{name}".lstrip("/") if prefix else name
            if child.type == "vos:ContainerNode":
                child_uri = join_uri(uri.rstrip("/"), name)
                self._walk_remote(child_uri + "/", rel, result)
            elif child.type in ("vos:DataNode", "vos:LinkNode"):
                child.setattr()
                is_link = child.type == "vos:LinkNode"
                target = child.target if is_link else None
                if target and "://" not in target:
                    target = self.fix_uri(target)
                md5 = child.props.get("MD5")
                size = int(child.attr.get("st_size", 0))
                if is_link and target:
                    target_info = self.get_node_info(target)
                    if target_info:
                        md5 = md5 or target_info.md5
                        size = size or target_info.size
                result[rel] = RemoteFile(
                    rel_path=rel,
                    uri=child.uri,
                    size=size,
                    mtime=float(child.attr.get("st_mtime", 0)),
                    md5=md5,
                    is_link=is_link,
                    link_target=target,
                )

    def remote_uri(self, base: str, rel_path: str) -> str:
        rel_path = rel_path.lstrip("/")
        return join_uri(base, rel_path)

    def get_node_info(self, uri: str) -> RemoteFile | None:
        uri = self.fix_uri(uri)
        try:
            node = self._client.get_node(uri, limit=None, force=True)
        except cadc_exceptions.NotFoundException:
            return None
        if node.type == "vos:ContainerNode":
            return None
        node.setattr()
        is_link = node.type == "vos:LinkNode"
        target = node.target if is_link else None
        if target and "://" not in target:
            target = self.fix_uri(target)
        return RemoteFile(
            rel_path=urlparse(uri).path.split("/")[-1],
            uri=uri,
            size=int(node.attr.get("st_size", 0)),
            mtime=float(node.attr.get("st_mtime", 0)),
            md5=node.props.get("MD5"),
            is_link=is_link,
            link_target=target,
        )

    def list_container_names(self, uri: str) -> list[str]:
        uri = self.fix_uri(uri.rstrip("/") + "/")
        try:
            return list(self._client.listdir(uri, force=True))
        except cadc_exceptions.NotFoundException:
            return []
