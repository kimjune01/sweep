"""Crash-safe filesystem helpers.

`atomic_write_text` writes to a sibling temp file and renames into place.
`rename` is atomic on POSIX, so either the file is there with full content
or it isn't there at all — never a partial write visible to readers.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> str:
    """Write content to path atomically. Returns sha256 of the bytes written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.encode()
    sha = hashlib.sha256(data).hexdigest()
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # atomic on POSIX
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return sha


def verify_receipt(path: Path, expected_sha: str) -> bool:
    """Re-hash the artifact and compare. Used by gate-pr-create to detect forgery."""
    if not path.exists():
        return False
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    return actual == expected_sha
