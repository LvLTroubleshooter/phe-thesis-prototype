"""Create graph outputs from Paillier/PHE + blockchain audit results."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import pandas as pd

DEFAULT_INPUT_PATH = Path("results/paillier_phe_blockchain/csv/batch_summary.csv")
DEFAULT_OUTPUT_DIR = Path("results/paillier_phe_blockchain/figures")


def load_results(input_path: str | Path) -> pd.DataFrame:
    """Load Paillier/PHE + blockchain summary rows from CSV."""
    return pd.read_csv(input_path)


def create_line_chart(
    results: pd.DataFrame,
    *,
    column: str,
    title: str,
    ylabel: str,
    output_path: str | Path,
) -> None:
    """Save one batch-size line chart."""
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(results["batch_size"], results[column], marker="o")
    ax.set_title(title)
    ax.set_xlabel("Batch size")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_paillier_phe_blockchain_visualizations(
    input_path: str | Path = DEFAULT_INPUT_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Create Stage 8 graph files."""
    results = load_results(input_path)
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    chart_specs = [
        (
            "total_runtime_s_mean",
            "Paillier/PHE + Blockchain Runtime By Batch Size",
            "Runtime (s)",
            "runtime.png",
        ),
        (
            "throughput_orders_per_second_mean",
            "Paillier/PHE + Blockchain Throughput By Batch Size",
            "Orders per second",
            "throughput.png",
        ),
        (
            "encryption_runtime_s_mean",
            "Paillier/PHE + Blockchain Encryption Time",
            "Runtime (s)",
            "encryption_time.png",
        ),
        (
            "encrypted_computation_runtime_s_mean",
            "Paillier/PHE + Blockchain Encrypted Computation Time",
            "Runtime (s)",
            "encrypted_computation_time.png",
        ),
        (
            "decryption_runtime_s_mean",
            "Paillier/PHE + Blockchain Decryption Time",
            "Runtime (s)",
            "decryption_time.png",
        ),
        (
            "ciphertext_size_bytes",
            "Paillier/PHE + Blockchain Ciphertext Size",
            "Estimated ciphertext size (bytes)",
            "ciphertext_size.png",
        ),
        (
            "blockchain_runtime_s_mean",
            "Paillier/PHE + Blockchain Audit Time",
            "Runtime (s)",
            "blockchain_time.png",
        ),
        (
            "blockchain_gas_used_total_mean",
            "Paillier/PHE + Blockchain Gas Used",
            "Gas used",
            "gas_used.png",
        ),
    ]

    output_paths: list[Path] = []
    for column, title, ylabel, filename in chart_specs:
        output_path = path / filename
        create_line_chart(
            results,
            column=column,
            title=title,
            ylabel=ylabel,
            output_path=output_path,
        )
        output_paths.append(output_path)
    return output_paths


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for Stage 8 visualizations."""
    parser = argparse.ArgumentParser(
        description="Create graph figures from Paillier/PHE + blockchain results."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Create Paillier/PHE + blockchain visualizations from command-line arguments."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    output_paths = create_paillier_phe_blockchain_visualizations(args.input, args.output_dir)

    print("Created Paillier/PHE + blockchain graphs:")
    for output_path in output_paths:
        print(output_path)


if __name__ == "__main__":
    main()
