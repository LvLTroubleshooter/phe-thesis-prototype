"""Generate dissertation-ready final comparison outputs."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Sequence

os.environ.setdefault("MPLCONFIGDIR", "/tmp/phe-thesis-matplotlib")

import matplotlib.pyplot as plt
import pandas as pd

from src.common.metrics import save_dataframe
from src.common.research_outputs import RAW_RUN_COLUMNS, BATCH_SUMMARY_COLUMNS

RESULTS_ROOT = Path("results")
FINAL_CSV_DIR = RESULTS_ROOT / "final_comparison/csv"
FINAL_FIGURES_DIR = RESULTS_ROOT / "final_comparison/figures"
FINAL_TABLES_DIR = RESULTS_ROOT / "final_comparison/tables"
BASELINE_VARIANT = "plaintext"


def print_progress(message: str = "") -> None:
    print(message, flush=True)


def discover_experiment_folders(results_root: str | Path = RESULTS_ROOT) -> list[Path]:
    """Return experiment result folders with batch_summary.csv files."""
    root = Path(results_root)
    if not root.exists():
        return []
    return sorted(
        folder
        for folder in root.iterdir()
        if folder.is_dir()
        and folder.name not in {"final_comparison", "datasets"}
        and (folder / "csv/batch_summary.csv").exists()
    )


def load_experiment_outputs(
    experiment_folders: Sequence[Path],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load all available raw runs, batch summaries, and manifest rows."""
    raw_frames: list[pd.DataFrame] = []
    summary_frames: list[pd.DataFrame] = []
    manifest_rows: list[dict[str, object]] = []

    for folder in experiment_folders:
        raw_path = folder / "csv/raw_runs.csv"
        summary_path = folder / "csv/batch_summary.csv"
        if summary_path.exists():
            summary = pd.read_csv(summary_path)
            summary_frames.append(normalize_summary(summary))
        if raw_path.exists():
            raw = pd.read_csv(raw_path)
            raw_frames.append(normalize_raw_runs(raw))
        manifest_rows.append(
            {
                "experiment_name": folder.name,
                "batch_summary_path": str(summary_path),
                "raw_runs_path": str(raw_path),
                "included": summary_path.exists(),
                "summary_row_count": len(pd.read_csv(summary_path)) if summary_path.exists() else 0,
                "raw_run_row_count": len(pd.read_csv(raw_path)) if raw_path.exists() else 0,
            }
        )

    all_raw = pd.concat(raw_frames, ignore_index=True) if raw_frames else pd.DataFrame(columns=RAW_RUN_COLUMNS)
    summaries = pd.concat(summary_frames, ignore_index=True) if summary_frames else pd.DataFrame(columns=BATCH_SUMMARY_COLUMNS)
    manifest = pd.DataFrame(manifest_rows)
    return all_raw, summaries, manifest


def normalize_raw_runs(raw: pd.DataFrame) -> pd.DataFrame:
    """Ensure raw runs have the expected schema."""
    result = raw.copy()
    for column in RAW_RUN_COLUMNS:
        if column not in result.columns:
            result[column] = "" if column in {"experiment_name", "variant", "batch_id", "run_id", "input_hash", "blockchain_transaction_hash", "created_at"} else 0
    return result[RAW_RUN_COLUMNS]


def normalize_summary(summary: pd.DataFrame) -> pd.DataFrame:
    """Ensure batch summaries have the expected schema."""
    result = summary.copy()
    for column in BATCH_SUMMARY_COLUMNS:
        if column not in result.columns:
            result[column] = "" if column in {"experiment_name", "variant", "batch_id", "input_hash"} else 0
    numeric_columns = [column for column in BATCH_SUMMARY_COLUMNS if column not in {"experiment_name", "variant", "batch_id", "input_hash", "correctness_pass"}]
    for column in numeric_columns:
        result[column] = pd.to_numeric(result[column], errors="coerce").fillna(0)
    result["correctness_pass"] = result["correctness_pass"].map(
        lambda value: str(value).strip().lower() in {"true", "1", "yes"}
    )
    return result[BATCH_SUMMARY_COLUMNS]


def variant_flags(variant: str) -> dict[str, object]:
    """Return descriptive layer flags for a variant."""
    return {
        "privacy_layer": "none" if "plaintext" in variant else "encryption",
        "auditability_layer": "blockchain" if "blockchain" in variant else "none",
        "blockchain_enabled": "blockchain" in variant,
        "encryption_enabled": any(token in variant for token in ["encryption", "paillier", "phe", "fhe"]),
    }


def create_comparison_summary(summaries: pd.DataFrame) -> pd.DataFrame:
    """Create final comparison rows with baseline-relative overheads."""
    if summaries.empty:
        return pd.DataFrame()
    baseline = summaries[summaries["variant"] == BASELINE_VARIANT][
        ["batch_id", "batch_size", "total_runtime_s_mean"]
    ].rename(columns={"total_runtime_s_mean": "baseline_runtime_s_mean"})
    merged = summaries.merge(baseline, on=["batch_id", "batch_size"], how="left")
    denominator = merged["baseline_runtime_s_mean"].replace(0, pd.NA)
    rows = []
    for _, row in merged.iterrows():
        slowdown = row["total_runtime_s_mean"] / denominator.loc[row.name] if pd.notna(denominator.loc[row.name]) else 0
        overhead = row["total_runtime_s_mean"] - row["baseline_runtime_s_mean"] if pd.notna(row["baseline_runtime_s_mean"]) else 0
        flags = variant_flags(str(row["variant"]))
        rows.append(
            {
                "variant": row["variant"],
                "batch_id": row["batch_id"],
                "batch_size": row["batch_size"],
                "total_runtime_s_mean": row["total_runtime_s_mean"],
                "total_runtime_s_median": row["total_runtime_s_median"],
                "total_runtime_s_std": row["total_runtime_s_std"],
                "throughput_orders_per_second_mean": row["throughput_orders_per_second_mean"],
                "matched_volume": row["matched_volume"],
                "matched_trades_count": row["matched_trades_count"],
                "unmatched_orders_count": row["unmatched_orders_count"],
                "correctness_pass": row["correctness_pass"],
                "relative_slowdown_vs_plaintext": slowdown,
                "runtime_overhead_s_vs_plaintext": overhead,
                "runtime_overhead_percent_vs_plaintext": (overhead / denominator.loc[row.name] * 100) if pd.notna(denominator.loc[row.name]) else 0,
                **flags,
            }
        )
    return pd.DataFrame(rows)


def create_overhead_breakdown(summaries: pd.DataFrame) -> pd.DataFrame:
    """Create runtime component and percentage breakdown rows."""
    rows = []
    for _, row in summaries.iterrows():
        total = row["total_runtime_s_mean"] or 0
        components = {
            "matching_runtime_s_mean": row["matching_runtime_s_mean"],
            "encryption_runtime_s_mean": row["encryption_runtime_s_mean"],
            "encrypted_computation_runtime_s_mean": row[
                "encrypted_computation_runtime_s_mean"
            ],
            "decryption_runtime_s_mean": row["decryption_runtime_s_mean"],
            "evidence_write_runtime_s_mean": row["audit_overhead_s_mean"] - row["blockchain_runtime_s_mean"],
            "hashing_runtime_s_mean": 0,
            "blockchain_runtime_s_mean": row["blockchain_runtime_s_mean"],
        }
        rows.append(
            {
                "variant": row["variant"],
                "batch_id": row["batch_id"],
                "batch_size": row["batch_size"],
                **components,
                "total_runtime_s_mean": total,
                "matching_percent": percentage(components["matching_runtime_s_mean"], total),
                "encryption_percent": percentage(components["encryption_runtime_s_mean"], total),
                "encrypted_computation_percent": percentage(components["encrypted_computation_runtime_s_mean"], total),
                "decryption_percent": percentage(components["decryption_runtime_s_mean"], total),
                "evidence_write_percent": percentage(components["evidence_write_runtime_s_mean"], total),
                "hashing_percent": 0,
                "blockchain_percent": percentage(components["blockchain_runtime_s_mean"], total),
            }
        )
    return pd.DataFrame(rows)


def percentage(value: float, total: float) -> float:
    return (value / total * 100) if total else 0.0


def create_correctness_comparison(summaries: pd.DataFrame) -> pd.DataFrame:
    """Compare every variant against plaintext by batch."""
    baseline = summaries[summaries["variant"] == BASELINE_VARIANT]
    rows = []
    for _, variant_row in summaries.iterrows():
        base = baseline[
            (baseline["batch_id"] == variant_row["batch_id"])
            & (baseline["batch_size"] == variant_row["batch_size"])
        ]
        if base.empty:
            continue
        base_row = base.iloc[0]
        rows.append(
            {
                "batch_id": variant_row["batch_id"],
                "batch_size": variant_row["batch_size"],
                "baseline_matched_volume": base_row["matched_volume"],
                "variant": variant_row["variant"],
                "variant_matched_volume": variant_row["matched_volume"],
                "matched_volume_difference": variant_row["matched_volume"] - base_row["matched_volume"],
                "baseline_matched_trades_count": base_row["matched_trades_count"],
                "variant_matched_trades_count": variant_row["matched_trades_count"],
                "matched_trades_difference": variant_row["matched_trades_count"] - base_row["matched_trades_count"],
                "baseline_unmatched_orders_count": base_row["unmatched_orders_count"],
                "variant_unmatched_orders_count": variant_row["unmatched_orders_count"],
                "unmatched_orders_difference": variant_row["unmatched_orders_count"] - base_row["unmatched_orders_count"],
                "input_hash_match": variant_row["input_hash"] == base_row["input_hash"],
                "trades_hash_match": "",
                "unmatched_hash_match": "",
                "correctness_pass": variant_row["correctness_pass"],
            }
        )
    return pd.DataFrame(rows)


def create_blockchain_overhead(summaries: pd.DataFrame) -> pd.DataFrame:
    """Create blockchain-only overhead rows."""
    blockchain = summaries[
        (summaries["blockchain_runtime_s_mean"] > 0)
        | (summaries["blockchain_gas_used_total_mean"] > 0)
    ].copy()
    if blockchain.empty:
        return pd.DataFrame(
            columns=[
                "variant",
                "batch_id",
                "batch_size",
                "evidence_write_runtime_s_mean",
                "hashing_runtime_s_mean",
                "blockchain_runtime_s_mean",
                "audit_overhead_s_mean",
                "audit_overhead_percent_mean",
                "gas_used_total_mean",
                "transaction_time_s_mean",
                "blockchain_tx_count_mean",
            ]
        )
    return pd.DataFrame(
        [
            {
                "variant": row["variant"],
                "batch_id": row["batch_id"],
                "batch_size": row["batch_size"],
                "evidence_write_runtime_s_mean": max(row["audit_overhead_s_mean"] - row["blockchain_runtime_s_mean"], 0),
                "hashing_runtime_s_mean": 0,
                "blockchain_runtime_s_mean": row["blockchain_runtime_s_mean"],
                "audit_overhead_s_mean": row["audit_overhead_s_mean"],
                "audit_overhead_percent_mean": row["audit_overhead_percent_mean"],
                "gas_used_total_mean": row["blockchain_gas_used_total_mean"],
                "transaction_time_s_mean": row["blockchain_runtime_s_mean"],
                "blockchain_tx_count_mean": row["blockchain_tx_count_mean"],
            }
            for _, row in blockchain.iterrows()
        ]
    )


def create_run_time_table(all_raw: pd.DataFrame) -> pd.DataFrame:
    """Create one readable row per experiment run with runtime in seconds."""
    columns = [
        "experiment_name",
        "variant",
        "batch_id",
        "batch_size",
        "run_id",
        "total_runtime_s",
    ]
    if all_raw.empty:
        return pd.DataFrame(columns=columns)
    table = all_raw.copy()
    if "is_warmup" in table.columns:
        table = table[
            table["is_warmup"].map(
                lambda value: str(value).strip().lower() not in {"true", "1", "yes"}
            )
        ].copy()
    for column in columns:
        if column not in table.columns:
            table[column] = "" if column in {"experiment_name", "variant", "batch_id", "run_id"} else 0
    for column in ["batch_size", "total_runtime_s"]:
        table[column] = pd.to_numeric(table[column], errors="coerce").fillna(0)
    return table[columns].sort_values(
        ["experiment_name", "batch_size", "batch_id", "run_id"]
    )


def validate_inputs(summaries: pd.DataFrame) -> list[str]:
    """Return validation warnings for comparison inputs."""
    warnings = []
    if summaries.empty:
        return ["No batch_summary.csv files found."]
    if BASELINE_VARIANT not in set(summaries["variant"]):
        warnings.append("Plaintext baseline is missing; relative slowdown cannot be computed.")
    batch_sets = summaries.groupby("variant")["batch_size"].apply(lambda values: set(values))
    if len({tuple(sorted(values)) for values in batch_sets}) > 1:
        warnings.append("Not every variant has the same batch sizes.")
    hash_counts = summaries.groupby(["batch_size"])["input_hash"].nunique()
    if (hash_counts > 1).any():
        warnings.append("At least one batch size has different input hashes across variants.")
    return warnings


def create_figures(
    comparison: pd.DataFrame,
    overhead: pd.DataFrame,
    correctness: pd.DataFrame,
    blockchain: pd.DataFrame,
    output_dir: str | Path = FINAL_FIGURES_DIR,
) -> list[Path]:
    """Create final comparison figures."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    figures: list[Path] = []
    if comparison.empty:
        return figures

    figures.append(line_by_variant(comparison, "total_runtime_s_mean", "Total runtime (s)", path / "01_total_runtime_comparison.png"))
    figures.append(
        line_by_variant(
            comparison,
            "throughput_orders_per_second_mean",
            "Orders per second (log scale)",
            path / "02_throughput_comparison.png",
            log_y=True,
        )
    )
    figures.append(stacked_runtime(overhead, path / "03_runtime_component_breakdown.png"))
    figures.append(line_by_variant(comparison, "relative_slowdown_vs_plaintext", "Slowdown vs plaintext (x)", path / "04_relative_slowdown_vs_baseline.png"))
    figures.append(bar_by_batch(blockchain, "audit_overhead_percent_mean", "Audit overhead (%)", path / "05_audit_overhead_percentage.png"))
    figures.append(grouped_bar(comparison, "matched_volume", "Matched volume", path / "06_correctness_matched_volume.png"))
    figures.append(bar_by_batch(blockchain, "gas_used_total_mean", "Gas used", path / "07_blockchain_gas_used.png"))
    figures.append(bar_by_batch(blockchain, "transaction_time_s_mean", "Transaction time (s)", path / "08_blockchain_transaction_time.png"))
    figures.append(loglog_runtime(comparison, path / "09_scalability_loglog_runtime.png"))
    return figures


def line_by_variant(
    data: pd.DataFrame,
    column: str,
    ylabel: str,
    output_path: Path,
    *,
    log_y: bool = False,
) -> Path:
    fig, ax = plt.subplots(figsize=(10, 6))
    for variant, rows in data.groupby("variant"):
        ordered = rows.sort_values("batch_size")
        ax.plot(ordered["batch_size"], ordered[column], marker="o", label=variant)
    ax.set_xlabel("Batch size")
    ax.set_ylabel(ylabel)
    if log_y and (data[column] > 0).any():
        ax.set_yscale("log")
    ax.grid(alpha=0.3, which="both")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def stacked_runtime(data: pd.DataFrame, output_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(12, 6))
    if data.empty:
        ax.text(0.5, 0.5, "No runtime component data", ha="center")
    else:
        labels = data["variant"] + "\n" + data["batch_size"].astype(str)
        bottom = pd.Series([0.0] * len(data))
        components = [
            ("matching_runtime_s_mean", "matching"),
            ("encryption_runtime_s_mean", "encryption"),
            ("encrypted_computation_runtime_s_mean", "encrypted computation"),
            ("decryption_runtime_s_mean", "decryption"),
            ("evidence_write_runtime_s_mean", "evidence writing"),
            ("hashing_runtime_s_mean", "hashing"),
            ("blockchain_runtime_s_mean", "blockchain"),
        ]
        positive_values: list[float] = []
        for column, label in components:
            values = data[column].fillna(0)
            positive_values.extend(float(value) for value in values if float(value) > 0)
            ax.bar(labels, values, bottom=bottom, label=label)
            bottom = bottom + values
        if positive_values:
            min_positive = min(positive_values)
            max_positive = max(positive_values)
            if max_positive / min_positive > 100:
                ax.set_yscale("symlog", linthresh=max(min_positive / 2, 1e-6))
                ax.set_ylabel("Runtime (s, symlog scale)")
                ax.text(
                    0.01,
                    0.98,
                    "Symlog scale used so small runtime components remain visible.",
                    transform=ax.transAxes,
                    va="top",
                    fontsize=9,
                    color="#444",
                )
            else:
                ax.set_ylabel("Runtime (s)")
        ax.legend()
    if data.empty:
        ax.set_ylabel("Runtime (s)")
    ax.tick_params(axis="x", rotation=35)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def grouped_bar(data: pd.DataFrame, column: str, ylabel: str, output_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 6))
    if data.empty or column not in data.columns:
        ax.text(0.5, 0.5, "No applicable data", ha="center", va="center")
        ax.set_xticks([])
    else:
        pivot = data.pivot(index="batch_size", columns="variant", values=column)
        pivot.plot(kind="bar", ax=ax)
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def bar_by_batch(data: pd.DataFrame, column: str, ylabel: str, output_path: Path) -> Path:
    return grouped_bar(data, column, ylabel, output_path)


def loglog_runtime(data: pd.DataFrame, output_path: Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 6))
    for variant, rows in data.groupby("variant"):
        ordered = rows.sort_values("batch_size")
        ax.plot(ordered["batch_size"], ordered["total_runtime_s_mean"], marker="o", label=variant)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Total runtime (s)")
    ax.grid(alpha=0.3, which="both")
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def write_thesis_tables(
    manifest: pd.DataFrame,
    comparison: pd.DataFrame,
    correctness: pd.DataFrame,
    blockchain: pd.DataFrame,
    run_times: pd.DataFrame,
    output_dir: str | Path = FINAL_TABLES_DIR,
) -> None:
    """Write compact thesis-ready CSV tables."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    save_dataframe(manifest, path / "thesis_table_experiment_config.csv")
    save_dataframe(
        run_times,
        path / "thesis_table_runtime_summary.csv",
    )
    save_dataframe(correctness, path / "thesis_table_correctness_summary.csv")
    save_dataframe(blockchain, path / "thesis_table_blockchain_overhead.csv")
    save_dataframe(run_times, path / "thesis_table_run_time_by_run.csv")


def generate_final_comparison(results_root: str | Path = RESULTS_ROOT) -> None:
    """Generate all final comparison CSVs, tables, and figures."""
    root = Path(results_root)
    final_csv_dir = root / "final_comparison/csv"
    final_figures_dir = root / "final_comparison/figures"
    final_tables_dir = root / "final_comparison/tables"

    folders = discover_experiment_folders(root)
    all_raw, summaries, manifest = load_experiment_outputs(folders)
    warnings = validate_inputs(summaries)
    comparison = create_comparison_summary(summaries)
    overhead = create_overhead_breakdown(summaries)
    correctness = create_correctness_comparison(summaries)
    blockchain = create_blockchain_overhead(summaries)
    run_times = create_run_time_table(all_raw)

    final_csv_dir.mkdir(parents=True, exist_ok=True)
    save_dataframe(all_raw, final_csv_dir / "all_raw_runs.csv")
    save_dataframe(comparison, final_csv_dir / "comparison_summary.csv")
    save_dataframe(correctness, final_csv_dir / "correctness_comparison.csv")
    save_dataframe(overhead, final_csv_dir / "overhead_breakdown.csv")
    save_dataframe(blockchain, final_csv_dir / "blockchain_overhead.csv")
    save_dataframe(run_times, final_csv_dir / "run_time_by_experiment_run.csv")
    save_dataframe(manifest, final_csv_dir / "experiment_manifest.csv")
    create_figures(comparison, overhead, correctness, blockchain, final_figures_dir)
    write_thesis_tables(
        manifest,
        comparison,
        correctness,
        blockchain,
        run_times,
        final_tables_dir,
    )
    for warning in warnings:
        print_progress(f"Warning: {warning}")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate final comparison outputs.")
    parser.add_argument("--results-root", type=Path, default=RESULTS_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    print_progress("Generating final comparison outputs...")
    generate_final_comparison(args.results_root)
    print_progress("Final comparison outputs saved to results/final_comparison/")


if __name__ == "__main__":
    main()
