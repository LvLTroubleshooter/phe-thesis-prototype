"""Project cleanup helpers for generated Python cache files."""

from __future__ import annotations

import shutil
from pathlib import Path


def clean_python_caches(root_path: str | Path = ".") -> list[Path]:
    """Remove Python __pycache__ folders under the given project root."""
    root = Path(root_path)
    removed_paths: list[Path] = []

    for cache_path in sorted(root.rglob("__pycache__")):
        if cache_path.is_dir():
            shutil.rmtree(cache_path)
            removed_paths.append(cache_path)

    return removed_paths
