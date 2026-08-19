"""MD5 helpers aligned with VOSpace node properties."""

from __future__ import annotations

import hashlib
from pathlib import Path

READ_SIZE = 2**19


def file_md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(READ_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
