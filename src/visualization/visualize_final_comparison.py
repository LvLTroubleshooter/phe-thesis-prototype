"""Create final comparison graph outputs from combined experiment results."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/phe-thesis-matplotlib")

import matplotlib.pyplot as plt
import pandas as pd

DEFAULT_OUTPUT_DIR = Path("results/final_comparison/figures")


def _prepare_output_path(output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def create_runtime_comparison_chart(
    results: pd.DataFrame,
    output_path: str | Path,
) -> Path:
    """Save total runtime by variant and batch size."""
    path = _prepare_output_path(output_path)
    runtime_column = "total_runtime_s" if "total_runtime_s" in results.columns else "total_runtime_ms"
    y_label = "Total runtime (s)" if runtime_column == "total_runtime_s" else "Total runtime (ms)"
    fig, ax = plt.subplots(figsize=(10, 6))
    for variant, rows in results.groupby("variant"):
        ordered = rows.sort_values("batch_size")
        ax.plot(
            ordered["batch_size"],
            ordered[runtime_column],
            marker="o",
            label=str(variant),
        )
    ax.set_title("Runtime By Variant And Batch Size")
    ax.set_xlabel("Batch size")
    ax.set_ylabel(y_label)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def create_throughput_comparison_chart(
    results: pd.DataFrame,
    output_path: str | Path,
) -> Path:
    """Save throughput by variant and batch size."""
    path = _prepare_output_path(output_path)
    fig, ax = plt.subplots(figsize=(10, 6))
    for variant, rows in results.groupby("variant"):
        ordered = rows.sort_values("batch_size")
        ax.plot(
            ordered["batch_size"],
            ordered["throughput_orders_per_second"],
            marker="o",
            label=str(variant),
        )
    ax.set_title("Throughput By Variant And Batch Size")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Orders per second")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def create_correctness_comparison_chart(
    results: pd.DataFrame,
    output_path: str | Path,
) -> Path:
    """Save correctness pass/fail counts by variant."""
    path = _prepare_output_path(output_path)
    correctness = results.copy()
    correctness["correctness_pass"] = correctness["correctness_pass"].astype(bool)
    grouped = (
        correctness.groupby(["variant", "correctness_pass"])
        .size()
        .unstack(fill_value=0)
    )
    passed = grouped.get(True, pd.Series(0, index=grouped.index))
    failed = grouped.get(False, pd.Series(0, index=grouped.index))

    fig, ax = plt.subplots(figsize=(10, 6))
    x_positions = range(len(grouped.index))
    ax.bar(x_positions, passed, label="Pass")
    ax.bar(x_positions, failed, bottom=passed, label="Fail")
    ax.set_title("Correctness By Variant")
    ax.set_xlabel("Variant")
    ax.set_ylabel("Rows")
    ax.set_xticks(list(x_positions))
    ax.set_xticklabels(grouped.index, rotation=20, ha="right")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def create_blockchain_overhead_chart(
    results: pd.DataFrame,
    output_path: str | Path,
) -> Path | None:
    """Save blockchain overhead by variant when blockchain data exists."""
    blockchain_rows = results[
        (results["blockchain_time_ms"].fillna(0) > 0)
        | (results["gas_used"].fillna(0) > 0)
    ]
    if blockchain_rows.empty:
        return None

    path = _prepare_output_path(output_path)
    grouped = blockchain_rows.groupby("variant").agg(
        blockchain_time_ms=("blockchain_time_ms", "mean"),
        gas_used=("gas_used", "mean"),
    )

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    grouped["blockchain_time_ms"].plot(kind="bar", ax=axes[0])
    axes[0].set_title("Mean Blockchain Time")
    axes[0].set_xlabel("Variant")
    axes[0].set_ylabel("Milliseconds")
    axes[0].grid(axis="y", alpha=0.3)

    grouped["gas_used"].plot(kind="bar", ax=axes[1], color="#4f7cff")
    axes[1].set_title("Mean Gas Used")
    axes[1].set_xlabel("Variant")
    axes[1].set_ylabel("Gas")
    axes[1].grid(axis="y", alpha=0.3)

    fig.suptitle("Blockchain Overhead By Variant")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def create_encryption_overhead_chart(
    results: pd.DataFrame,
    output_path: str | Path,
) -> Path | None:
    """Save encryption overhead by variant when encryption data exists."""
    encryption_rows = results[
        (results["encryption_time_ms"].fillna(0) > 0)
        | (results["decryption_time_ms"].fillna(0) > 0)
        | (results["encrypted_computation_time_ms"].fillna(0) > 0)
    ]
    if encryption_rows.empty:
        return None

    path = _prepare_output_path(output_path)
    grouped = encryption_rows.groupby("variant").agg(
        encryption_time_ms=("encryption_time_ms", "mean"),
        encrypted_computation_time_ms=("encrypted_computation_time_ms", "mean"),
        decryption_time_ms=("decryption_time_ms", "mean"),
    )

    fig, ax = plt.subplots(figsize=(10, 6))
    grouped.plot(kind="bar", ax=ax)
    ax.set_title("Encryption Overhead By Variant")
    ax.set_xlabel("Variant")
    ax.set_ylabel("Milliseconds")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def create_final_comparison_visualizations(
    results: pd.DataFrame,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Create all final comparison graph files that have applicable data."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    output_paths = [
        create_runtime_comparison_chart(
            results,
            path / "runtime_by_variant_and_batch_size.png",
        ),
        create_throughput_comparison_chart(
            results,
            path / "throughput_by_variant_and_batch_size.png",
        ),
        create_correctness_comparison_chart(
            results,
            path / "correctness_by_variant.png",
        ),
    ]

    blockchain_path = create_blockchain_overhead_chart(
        results,
        path / "blockchain_overhead_by_variant.png",
    )
    if blockchain_path is not None:
        output_paths.append(blockchain_path)

    encryption_path = create_encryption_overhead_chart(
        results,
        path / "encryption_overhead_by_variant.png",
    )
    if encryption_path is not None:
        output_paths.append(encryption_path)

    return output_paths
