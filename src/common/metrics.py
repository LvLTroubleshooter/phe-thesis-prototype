"""Shared metric helpers for prototype experiments."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

COMMON_RESULT_COLUMNS = [
    "variant",
    "batch_id",
    "batch_size",
    "buy_volume",
    "sell_volume",
    "matched_volume",
    "executed_trade_count",
    "correctness_pass",
    "total_runtime_ms",
    "total_runtime_s",
    "throughput_orders_per_second",
    "encryption_time_ms",
    "encrypted_computation_time_ms",
    "decryption_time_ms",
    "ciphertext_size_bytes",
    "blockchain_time_ms",
    "gas_used",
    "block_number",
    "transaction_hash",
]

TEXT_DEFAULT_COLUMNS = {
    "variant",
    "batch_id",
    "transaction_hash",
}


def default_common_result_value(column: str) -> object:
    """Return the default value for a common ablation result column."""
    if column in TEXT_DEFAULT_COLUMNS:
        return ""
    if column == "correctness_pass":
        return False
    return 0


def calculate_throughput(item_count: int, runtime_seconds: float) -> float:
    """Calculate processed items per second."""
    if runtime_seconds <= 0:
        return 0.0
    return item_count / runtime_seconds


def seconds_to_milliseconds(runtime_seconds: float) -> float:
    """Convert seconds to milliseconds."""
    return runtime_seconds * 1_000


def save_dataframe(dataframe: pd.DataFrame, output_path: str | Path) -> None:
    """Save a DataFrame to CSV, creating parent folders when needed."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(path, index=False)


def append_dataframe(
    dataframe: pd.DataFrame,
    output_path: str | Path,
    *,
    include_header: bool,
) -> None:
    """Append a DataFrame to a CSV file, creating parent folders when needed."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(path, mode="a", header=include_header, index=False)


def reset_output_file(output_path: str | Path) -> None:
    """Remove a previous output file before streaming a fresh experiment run."""
    path = Path(output_path)
    if path.exists():
        path.unlink()


def file_size_bytes(path: str | Path) -> int:
    """Return file size in bytes, or zero when the file does not exist."""
    file_path = Path(path)
    return file_path.stat().st_size if file_path.exists() else 0


def apply_common_result_schema(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Ensure a result DataFrame contains the common ablation-study columns."""
    result = dataframe.copy()
    for column in COMMON_RESULT_COLUMNS:
        if column not in result.columns:
            result[column] = default_common_result_value(column)

    extra_columns = [
        column for column in result.columns if column not in COMMON_RESULT_COLUMNS
    ]
    return result[COMMON_RESULT_COLUMNS + extra_columns]
