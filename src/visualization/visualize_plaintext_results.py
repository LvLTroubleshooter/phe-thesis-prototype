"""Create graph outputs from plaintext baseline results."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import pandas as pd

DEFAULT_INPUT_PATH = Path("results/plaintext_baseline/csv/batch_summary.csv")
DEFAULT_OUTPUT_DIR = Path("results/plaintext_baseline/figures")


def load_results(input_path: str | Path) -> pd.DataFrame:
    """Load plaintext baseline result rows from CSV."""
    return pd.read_csv(input_path)


def create_volume_chart(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save a bar chart comparing buy, sell, and matched volume by batch."""
    x_labels = results["batch_size"].astype(str)
    x_positions = range(len(results))
    width = 0.25
    buy_volume = results["buy_volume"] if "buy_volume" in results.columns else results["matched_volume"]
    sell_volume = results["sell_volume"] if "sell_volume" in results.columns else results["matched_volume"]
    matched_volume = results["matched_volume"] if "matched_volume" in results.columns else results["matched_volume"]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(
        [position - width for position in x_positions],
        buy_volume,
        width=width,
        label="Buy volume",
    )
    ax.bar(
        x_positions,
        sell_volume,
        width=width,
        label="Sell volume",
    )
    ax.bar(
        [position + width for position in x_positions],
        matched_volume,
        width=width,
        label="Matched volume",
    )
    ax.set_title("Plaintext Baseline Volumes By Batch Size")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Volume")
    ax.set_xticks(list(x_positions))
    ax.set_xticklabels(x_labels)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_runtime_chart(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save a total runtime chart by batch size."""
    runtime = (
        results["total_runtime_s_mean"]
        if "total_runtime_s_mean" in results.columns
        else results["total_runtime_ms"] / 1_000
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(
        results["batch_size"],
        runtime,
        marker="o",
    )
    ax.set_title("Plaintext Baseline Runtime By Batch Size")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Runtime (s)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_throughput_chart(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save a throughput chart by batch size."""
    throughput = (
        results["throughput_orders_per_second_mean"]
        if "throughput_orders_per_second_mean" in results.columns
        else results["throughput_orders_per_second"]
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(
        results["batch_size"],
        throughput,
        marker="o",
    )
    ax.set_title("Plaintext Baseline Throughput By Batch Size")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Orders per second")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_plaintext_visualizations(
    input_path: str | Path = DEFAULT_INPUT_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Create graph files from plaintext baseline results."""
    results = load_results(input_path)
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    output_paths = [
        path / "plaintext_baseline_volumes.png",
        path / "plaintext_baseline_runtime.png",
        path / "plaintext_baseline_throughput.png",
    ]
    create_volume_chart(results, output_paths[0])
    create_runtime_chart(results, output_paths[1])
    create_throughput_chart(results, output_paths[2])
    return output_paths


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for plaintext visualization."""
    parser = argparse.ArgumentParser(
        description="Create graph figures from plaintext baseline results."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Create plaintext result visualizations from command-line arguments."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    output_paths = create_plaintext_visualizations(args.input, args.output_dir)

    print("Created plaintext baseline graphs:")
    for output_path in output_paths:
        print(output_path)


if __name__ == "__main__":
    main()
