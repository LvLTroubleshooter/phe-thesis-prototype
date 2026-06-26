"""Create graph outputs from Paillier/PHE aggregation results."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt
import pandas as pd

DEFAULT_INPUT_PATH = Path("results/paillier_phe/csv/batch_summary.csv")
DEFAULT_OUTPUT_DIR = Path("results/paillier_phe/figures")


def load_results(input_path: str | Path) -> pd.DataFrame:
    """Load Paillier/PHE result rows from CSV."""
    return pd.read_csv(input_path)


def create_runtime_chart(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save a total runtime chart by batch size."""
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(
        results["batch_size"],
        results["total_runtime_s_mean"],
        marker="o",
    )
    ax.set_title("Paillier/PHE Runtime By Batch Size")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Runtime (s)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_throughput_chart(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save a throughput chart by batch size."""
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(
        results["batch_size"],
        results["throughput_orders_per_second_mean"],
        marker="o",
    )
    ax.set_title("Paillier/PHE Throughput By Batch Size")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Orders per second")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_component_chart(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save an encryption/computation/decryption component chart."""
    labels = results["batch_size"].astype(str)
    x_positions = range(len(results))
    bottom = pd.Series([0.0] * len(results))
    components = [
        ("encryption_runtime_s_mean", "encryption"),
        ("encrypted_computation_runtime_s_mean", "encrypted aggregation"),
        ("decryption_runtime_s_mean", "decryption"),
    ]

    fig, ax = plt.subplots(figsize=(10, 6))
    for column, label in components:
        values = results[column].fillna(0) if column in results.columns else 0
        ax.bar(x_positions, values, bottom=bottom, label=label)
        bottom = bottom + values
    ax.set_title("Paillier/PHE Runtime Components")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Runtime (s)")
    ax.set_xticks(list(x_positions))
    ax.set_xticklabels(labels)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_ciphertext_size_chart(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save a ciphertext-size chart by batch size."""
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(
        results["batch_size"],
        results["ciphertext_size_bytes"],
        marker="o",
    )
    ax.set_title("Paillier/PHE Ciphertext Size By Batch Size")
    ax.set_xlabel("Batch size")
    ax.set_ylabel("Estimated ciphertext size (bytes)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=200)
    plt.close(fig)


def create_paillier_phe_visualizations(
    input_path: str | Path = DEFAULT_INPUT_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> list[Path]:
    """Create graph files from Paillier/PHE results."""
    results = load_results(input_path)
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    output_paths = [
        path / "paillier_phe_runtime.png",
        path / "paillier_phe_throughput.png",
        path / "paillier_phe_components.png",
        path / "paillier_phe_ciphertext_size.png",
    ]
    create_runtime_chart(results, output_paths[0])
    create_throughput_chart(results, output_paths[1])
    create_component_chart(results, output_paths[2])
    create_ciphertext_size_chart(results, output_paths[3])
    return output_paths


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for Paillier/PHE visualization."""
    parser = argparse.ArgumentParser(
        description="Create graph figures from Paillier/PHE aggregation results."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Create Paillier/PHE visualizations from command-line arguments."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    output_paths = create_paillier_phe_visualizations(args.input, args.output_dir)

    print("Created Paillier/PHE graphs:")
    for output_path in output_paths:
        print(output_path)


if __name__ == "__main__":
    main()
