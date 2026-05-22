"""Research-ready output schemas and helpers for experiment evidence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean, median, stdev
from typing import Iterable

import pandas as pd

from src.common.file_hashing import sha256_file, sha256_mapping
from src.common.metrics import save_dataframe

DATASET_MANIFEST_COLUMNS = [
    "batch_id",
    "batch_size",
    "seed",
    "dataset_path",
    "input_orders_count",
    "buy_orders_count",
    "sell_orders_count",
    "buy_volume",
    "sell_volume",
    "input_hash",
    "created_at",
]

RAW_RUN_COLUMNS = [
    "experiment_name",
    "variant",
    "batch_id",
    "batch_size",
    "run_id",
    "is_warmup",
    "seed",
    "input_hash",
    "matching_runtime_s",
    "encryption_runtime_s",
    "encrypted_computation_runtime_s",
    "decryption_runtime_s",
    "evidence_write_runtime_s",
    "hashing_runtime_s",
    "blockchain_runtime_s",
    "total_runtime_s",
    "throughput_orders_per_second",
    "matched_volume",
    "matched_trades_count",
    "unmatched_orders_count",
    "correctness_pass",
    "blockchain_tx_count",
    "blockchain_gas_used_total",
    "blockchain_block_number",
    "blockchain_transaction_hash",
    "created_at",
]

BATCH_SUMMARY_COLUMNS = [
    "experiment_name",
    "variant",
    "batch_id",
    "batch_size",
    "seed",
    "measured_runs",
    "warmup_runs",
    "input_hash",
    "matching_runtime_s_mean",
    "matching_runtime_s_median",
    "matching_runtime_s_std",
    "matching_runtime_s_min",
    "matching_runtime_s_max",
    "batch_wall_clock_runtime_s",
    "experiment_wall_clock_runtime_s",
    "command_wall_clock_runtime_s",
    "command_wall_clock_runtime_ms",
    "total_runtime_s_mean",
    "total_runtime_s_median",
    "total_runtime_s_std",
    "total_runtime_s_min",
    "total_runtime_s_max",
    "throughput_orders_per_second_mean",
    "throughput_orders_per_second_median",
    "throughput_orders_per_second_std",
    "matched_volume",
    "matched_trades_count",
    "unmatched_orders_count",
    "correctness_pass",
    "audit_overhead_s_mean",
    "audit_overhead_percent_mean",
    "blockchain_runtime_s_mean",
    "blockchain_tx_count_mean",
    "blockchain_gas_used_total_mean",
]

BLOCKCHAIN_AUDIT_COLUMNS = [
    "experiment_name",
    "variant",
    "batch_id",
    "batch_size",
    "input_hash",
    "trades_hash",
    "unmatched_hash",
    "result_hash",
    "evidence_root_hash",
    "contract_address",
    "transaction_hash",
    "block_number",
    "gas_used",
    "transaction_time_s",
    "confirmation_time_s",
    "tx_submitted_at_wall_time",
    "tx_mined_at_wall_time",
    "tx_confirmed_at_wall_time",
    "tx_submission_time_s",
    "tx_submission_to_mined_s",
    "tx_mined_to_confirmed_s",
    "tx_total_confirmation_s",
    "pending_block_distance",
    "included_block_number",
    "confirmed_at_block_number",
    "included_block_timestamp",
    "confirmed_block_timestamp",
    "base_fee_per_gas",
    "max_fee_per_gas",
    "max_priority_fee_per_gas",
    "effective_gas_price",
    "block_gas_limit",
    "block_gas_used",
    "block_gas_used_percent",
    "transaction_index",
    "nonce",
    "target_confirmations",
    "submission_mode",
    "revert_reason_if_failed",
    "status",
    "created_at",
]


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(UTC).isoformat()


def std_or_zero(values: Iterable[float]) -> float:
    """Return sample standard deviation, or zero when fewer than two values exist."""
    items = list(values)
    return stdev(items) if len(items) > 1 else 0.0


def write_dataset_manifest(
    orders: pd.DataFrame,
    seed: int,
    output_path: str | Path = "results/datasets/dataset_manifest.csv",
    dataset_dir: str | Path = "results/datasets/synthetic_orders",
) -> pd.DataFrame:
    """Write one per-batch dataset file plus a dataset manifest."""
    dataset_path = Path(dataset_dir)
    dataset_path.mkdir(parents=True, exist_ok=True)
    created_at = utc_now_iso()
    rows: list[dict[str, object]] = []

    for _, batch_orders in orders.groupby("batch_id", sort=True):
        batch_id = str(batch_orders["batch_id"].iloc[0])
        batch_file = dataset_path / f"{batch_id}.csv"
        save_dataframe(batch_orders, batch_file)
        rows.append(
            {
                "batch_id": batch_id,
                "batch_size": int(len(batch_orders)),
                "seed": seed,
                "dataset_path": str(batch_file),
                "input_orders_count": int(len(batch_orders)),
                "buy_orders_count": int((batch_orders["side"] == "BUY").sum()),
                "sell_orders_count": int((batch_orders["side"] == "SELL").sum()),
                "buy_volume": int(batch_orders.loc[batch_orders["side"] == "BUY", "quantity"].sum()),
                "sell_volume": int(batch_orders.loc[batch_orders["side"] == "SELL", "quantity"].sum()),
                "input_hash": sha256_file(batch_file),
                "created_at": created_at,
            }
        )

    manifest = pd.DataFrame(rows, columns=DATASET_MANIFEST_COLUMNS)
    save_dataframe(manifest, output_path)
    return manifest


def manifest_by_batch(manifest: pd.DataFrame) -> dict[str, dict[str, object]]:
    """Return dataset manifest rows keyed by batch_id."""
    return {
        str(row["batch_id"]): row.to_dict()
        for _, row in manifest.iterrows()
    }


def summarize_measured_runs(
    raw_runs: pd.DataFrame,
    *,
    experiment_name: str,
    variant: str,
    seed: int,
    warmup_runs: int,
    measured_runs: int,
) -> pd.DataFrame:
    """Create batch summaries from measured raw-run rows only."""
    measured = raw_runs[raw_runs["is_warmup"] == False].copy()
    rows: list[dict[str, object]] = []

    for _, group in measured.groupby("batch_id", sort=True):
        matching = group["matching_runtime_s"].astype(float)
        total = group["total_runtime_s"].astype(float)
        throughput = group["throughput_orders_per_second"].astype(float)
        audit = (
            group["evidence_write_runtime_s"].astype(float)
            + group["hashing_runtime_s"].astype(float)
            + group["blockchain_runtime_s"].astype(float)
        )
        matching_denominator = matching.replace(0, pd.NA)
        audit_percent = (audit / matching_denominator * 100).fillna(0)

        rows.append(
            {
                "experiment_name": experiment_name,
                "variant": variant,
                "batch_id": group["batch_id"].iloc[0],
                "batch_size": int(group["batch_size"].iloc[0]),
                "seed": seed,
                "measured_runs": measured_runs,
                "warmup_runs": warmup_runs,
                "input_hash": group["input_hash"].iloc[0],
                "matching_runtime_s_mean": fmean(matching),
                "matching_runtime_s_median": median(matching),
                "matching_runtime_s_std": std_or_zero(matching),
                "matching_runtime_s_min": min(matching),
                "matching_runtime_s_max": max(matching),
                "total_runtime_s_mean": fmean(total),
                "total_runtime_s_median": median(total),
                "total_runtime_s_std": std_or_zero(total),
                "total_runtime_s_min": min(total),
                "total_runtime_s_max": max(total),
                "throughput_orders_per_second_mean": fmean(throughput),
                "throughput_orders_per_second_median": median(throughput),
                "throughput_orders_per_second_std": std_or_zero(throughput),
                "matched_volume": int(group["matched_volume"].iloc[-1]),
                "matched_trades_count": int(group["matched_trades_count"].iloc[-1]),
                "unmatched_orders_count": int(group["unmatched_orders_count"].iloc[-1]),
                "correctness_pass": bool(group["correctness_pass"].all()),
                "audit_overhead_s_mean": fmean(audit),
                "audit_overhead_percent_mean": fmean(audit_percent),
                "blockchain_runtime_s_mean": fmean(group["blockchain_runtime_s"].astype(float)),
                "blockchain_tx_count_mean": fmean(group["blockchain_tx_count"].astype(float)),
                "blockchain_gas_used_total_mean": fmean(group["blockchain_gas_used_total"].astype(float)),
            }
        )

    return pd.DataFrame(rows, columns=BATCH_SUMMARY_COLUMNS)


def apply_wall_clock_runtime_columns(
    summary: pd.DataFrame,
    batch_wall_clock_runtime_s: dict[str, float],
    experiment_wall_clock_runtime_s: float = 0.0,
) -> pd.DataFrame:
    """Use wall-clock batch runtime as the human-facing total runtime."""
    result = summary.copy()
    if result.empty:
        return result

    for index, row in result.iterrows():
        batch_id = str(row["batch_id"])
        batch_runtime = float(batch_wall_clock_runtime_s.get(batch_id, 0.0))
        if batch_runtime <= 0:
            batch_runtime = float(row.get("total_runtime_s_mean", 0.0))
        batch_size = int(row.get("batch_size", 0))
        throughput = batch_size / batch_runtime if batch_runtime > 0 else 0.0

        result.at[index, "batch_wall_clock_runtime_s"] = batch_runtime
        result.at[index, "experiment_wall_clock_runtime_s"] = experiment_wall_clock_runtime_s
        result.at[index, "command_wall_clock_runtime_s"] = 0.0
        result.at[index, "command_wall_clock_runtime_ms"] = 0.0
        result.at[index, "total_runtime_s_mean"] = batch_runtime
        result.at[index, "total_runtime_s_median"] = batch_runtime
        result.at[index, "total_runtime_s_std"] = 0.0
        result.at[index, "total_runtime_s_min"] = batch_runtime
        result.at[index, "total_runtime_s_max"] = batch_runtime
        result.at[index, "throughput_orders_per_second_mean"] = throughput
        result.at[index, "throughput_orders_per_second_median"] = throughput
        result.at[index, "throughput_orders_per_second_std"] = 0.0

    return result[BATCH_SUMMARY_COLUMNS]


def write_command_wall_clock_runtime(
    summary_path: str | Path,
    command_wall_clock_runtime_s: float,
) -> None:
    """Persist the full CLI command runtime into an existing batch summary CSV."""
    path = Path(summary_path)
    if not path.exists():
        return
    summary = pd.read_csv(path)
    summary["command_wall_clock_runtime_s"] = command_wall_clock_runtime_s
    summary["command_wall_clock_runtime_ms"] = command_wall_clock_runtime_s * 1_000
    save_dataframe(summary, path)


def result_hash_from_summary_row(row: pd.Series) -> str:
    """Hash stable batch summary values for audit evidence."""
    return sha256_mapping(
        {
            "variant": row["variant"],
            "batch_id": row["batch_id"],
            "batch_size": int(row["batch_size"]),
            "matched_volume": int(row["matched_volume"]),
            "matched_trades_count": int(row["matched_trades_count"]),
            "unmatched_orders_count": int(row["unmatched_orders_count"]),
            "correctness_pass": bool(row["correctness_pass"]),
        }
    )
