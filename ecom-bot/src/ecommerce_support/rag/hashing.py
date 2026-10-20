"""Deterministic content hashing for document/chunk dedupe (DATA-006).

A stable SHA-256 digest is the dedupe key: an unchanged document (same normalized text, same
tenant/source) must not create a new version, and identical chunks within a document are stored
once. The hash is content-only (no timestamps), so it is reproducible across runs and processes.
"""

from __future__ import annotations

import hashlib

_ALGORITHM = "sha256"


def content_hash(value: str | bytes, *, algorithm: str = _ALGORITHM) -> str:
    """Return the hex digest of ``value`` using ``algorithm`` (default SHA-256)."""
    if isinstance(value, str):
        payload = value.encode("utf-8")
    elif isinstance(value, bytes):
        payload = value
    else:
        raise TypeError("content_hash expects str or bytes")
    return hashlib.new(algorithm, payload).hexdigest()
