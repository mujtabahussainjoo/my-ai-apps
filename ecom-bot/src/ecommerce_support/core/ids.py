"""Opaque, prefixed identifier generation shared across services and repositories."""

from __future__ import annotations

import secrets

_ID_BYTES = 12


def new_id(prefix: str) -> str:
    """Return a new opaque identifier such as ``conv_9f2c...``.

    IDs are prefixed (for readability/traceability) and random (not enumerable).
    """
    return f"{prefix}_{secrets.token_hex(_ID_BYTES)}"
