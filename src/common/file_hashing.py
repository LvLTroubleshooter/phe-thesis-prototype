"""Stable hashing helpers for experiment evidence files and result rows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


def sha256_file(path: str | Path) -> str:
    """Return the SHA-256 hex digest for a file."""
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    """Return the SHA-256 hex digest for UTF-8 text."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_for_hash(value: Any) -> Any:
    """Convert common dataframe/numeric values into JSON-stable values."""
    if hasattr(value, "item"):
        return normalize_for_hash(value.item())
    if isinstance(value, float):
        return round(value, 12)
    if isinstance(value, dict):
        return {str(key): normalize_for_hash(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_for_hash(item) for item in value]
    return value


def sha256_mapping(mapping: Mapping[str, Any]) -> str:
    """Return a stable SHA-256 hex digest for a mapping."""
    normalized = normalize_for_hash(dict(mapping))
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
    return sha256_text(payload)


def hex_digest_to_bytes32(hex_digest: str) -> bytes:
    """Convert a 64-character SHA-256 hex digest into bytes32."""
    if len(hex_digest) != 64:
        raise ValueError("hex_digest must be 64 hex characters")
    return bytes.fromhex(hex_digest)
