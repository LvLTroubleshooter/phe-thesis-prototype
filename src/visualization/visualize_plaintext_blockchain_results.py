"""Create graph outputs from plaintext blockchain audit results."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import pandas as pd

DEFAULT_INPUT_PATH = Path(
    "results/plaintext_blockchain/csv/batch_summary.csv"
)
DEFAULT_OUTPUT_DIR = Path("results/plaintext_blockchain/figures")


def load_results(input_path: str | Path) -> pd.DataFrame:
    """Load plaintext blockchain result rows from CSV."""
    return pd.read_csv(input_path)


def create_gas_chart(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save a gas-used bar chart."""
    gas = (
        results["blockchain_gas_used_total_mean"]
        if "blockchain_gas_used_total_mean" in results.columns
        else results["gas_used"]
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(results["batch_id"], gas)
    ax.set_title("Plaintext Blockchain Gas Used By Batch")
    ax.set_xlabel("Batch")
    ax.set_ylabel("Gas used")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_transaction_time_chart(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save a blockchain-time bar chart."""
    runtime = (
        results["blockchain_runtime_s_mean"]
        if "blockchain_runtime_s_mean" in results.columns
        else results["blockchain_time_ms"] / 1_000
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(results["batch_id"], runtime)
    ax.set_title("Plaintext Blockchain Time By Batch")
    ax.set_xlabel("Batch")
    ax.set_ylabel("Blockchain time (s)")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_block_chart(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save a chart showing which block recorded each batch."""
    value = (
        results["blockchain_tx_count_mean"]
        if "blockchain_tx_count_mean" in results.columns
        else results["block_number"]
    )
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(results["batch_id"], value, marker="o")
    ax.set_title("Plaintext Blockchain Audit Block Numbers")
    ax.set_xlabel("Batch")
    ax.set_ylabel("Blockchain transactions")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_plaintext_blockchain_visualizations(
    input_path: str | Path = DEFAULT_INPUT_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Create graph files from plaintext blockchain results."""
    results = load_results(input_path)
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    output_paths = [
        path / "plaintext_blockchain_gas_used.png",
        path / "plaintext_blockchain_transaction_time.png",
        path / "plaintext_blockchain_blocks.png",
    ]
    create_gas_chart(results, output_paths[0])
    create_transaction_time_chart(results, output_paths[1])
    create_block_chart(results, output_paths[2])
    return output_paths


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for plaintext blockchain visualizations."""
    parser = argparse.ArgumentParser(
        description="Create graph figures from plaintext blockchain results."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Create plaintext blockchain visualizations from command-line arguments."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    output_paths = create_plaintext_blockchain_visualizations(args.input, args.output_dir)

    print("Created plaintext blockchain graphs:")
    for output_path in output_paths:
        print(output_path)


if __name__ == "__main__":
    main()
