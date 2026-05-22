from pathlib import Path

import pytest

from src.common.file_hashing import (
    hex_digest_to_bytes32,
    sha256_file,
    sha256_mapping,
    sha256_text,
)


def test_sha256_file_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "example.txt"
    path.write_text("abc", encoding="utf-8")

    assert sha256_file(path) == sha256_text("abc")


def test_sha256_mapping_is_order_independent() -> None:
    first = sha256_mapping({"batch_id": "batch_0001", "matched_volume": 10})
    second = sha256_mapping({"matched_volume": 10, "batch_id": "batch_0001"})

    assert first == second


def test_hex_digest_to_bytes32_requires_sha256_length() -> None:
    digest = sha256_text("abc")

    assert len(hex_digest_to_bytes32(digest)) == 32

    with pytest.raises(ValueError, match="64 hex characters"):
        hex_digest_to_bytes32("abc")
