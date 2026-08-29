"""Deterministic serialization shared by scientific-control artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(payload: Any) -> bytes:
    return (
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
