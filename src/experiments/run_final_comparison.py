"""Generate final comparison outputs from available experiment result CSVs."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import pandas as pd

from src.common.metrics import (
    COMMON_RESULT_COLUMNS,
    apply_common_result_schema,
    save_dataframe,
)
from src.visualization.visualize_final_comparison import (
    DEFAULT_OUTPUT_DIR as DEFAULT_FIGURES_DIR,
    create_final_comparison_visualizations,
)

DEFAULT_RESULTS_ROOT = Path("results")
DEFAULT_OUTPUT_DIR = Path("results/final_comparison/csv")
DEFAULT_COMPARISON_PATH = DEFAULT_OUTPUT_DIR / "final_comparison.csv"
DEFAULT_SUMMARY_PATH = DEFAULT_OUTPUT_DIR / "final_comparison_summary.csv"
DEFAULT_AVAILABLE_EXPERIMENTS_PATH = DEFAULT_OUTPUT_DIR / "available_experiments.csv"

NUMERIC_COMMON_COLUMNS = [
    column
    for column in COMMON_RESULT_COLUMNS
    if column not in {"variant", "batch_id", "transaction_hash", "correctness_pass"}
]


def print_progress(message: str = "") -> None:
    """Print simple terminal progress immediately."""
    print(message, flush=True)


def discover_experiment_result_csvs(
    results_root: str | Path = DEFAULT_RESULTS_ROOT,
) -> list[Path]:
    """Find experiment result CSVs, excluding final comparison outputs."""
    root = Path(results_root)
    if not root.exists():
        return []

    paths = sorted(root.glob("*/csv/*_results.csv"))
    return [
        path
        for path in paths
        if path.parts[: len((root / "final_comparison").parts)]
        != (root / "final_comparison").parts
    ]


def experiment_name_from_csv_path(path: str | Path) -> str:
    """Return the experiment folder name for a discovered result CSV."""
    csv_path = Path(path)
    return csv_path.parents[1].name


def normalize_result_rows(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Normalize a result DataFrame to the simple common ablation schema."""
    normalized = apply_common_result_schema(dataframe)
    normalized = normalized.copy()

    for column in NUMERIC_COMMON_COLUMNS:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce").fillna(0)
    normalized["total_runtime_s"] = pd.to_numeric(
        normalized.get("total_runtime_s", 0), errors="coerce"
    ).fillna(0).astype(float)
    missing_runtime_s = (normalized["total_runtime_s"] == 0) & (
        normalized["total_runtime_ms"] > 0
    )
    normalized.loc[missing_runtime_s, "total_runtime_s"] = (
        normalized.loc[missing_runtime_s, "total_runtime_ms"] / 1_000
    )

    if "audit_overhead_s" not in normalized.columns:
        normalized["audit_overhead_s"] = normalized["blockchain_time_ms"] / 1_000
    else:
        normalized["audit_overhead_s"] = pd.to_numeric(
            normalized["audit_overhead_s"], errors="coerce"
        ).fillna(normalized["blockchain_time_ms"] / 1_000)

    if "matching_runtime_s_mean" not in normalized.columns:
        normalized["matching_runtime_s_mean"] = normalized["total_runtime_s"]
    else:
        normalized["matching_runtime_s_mean"] = pd.to_numeric(
            normalized["matching_runtime_s_mean"], errors="coerce"
        ).fillna(normalized["total_runtime_s"])

    if "audit_overhead_percent" not in normalized.columns:
        denominator = normalized["matching_runtime_s_mean"].replace(0, pd.NA)
        normalized["audit_overhead_percent"] = (
            normalized["audit_overhead_s"] / denominator * 100
        ).fillna(0)
    else:
        normalized["audit_overhead_percent"] = pd.to_numeric(
            normalized["audit_overhead_percent"], errors="coerce"
        ).fillna(0)

    normalized["correctness_pass"] = (
        normalized["correctness_pass"]
        .fillna(False)
        .map(lambda value: str(value).strip().lower() in {"true", "1", "yes"})
    )
    normalized["variant"] = normalized["variant"].fillna("").astype(str)
    normalized["batch_id"] = normalized["batch_id"].fillna("").astype(str)
    normalized["transaction_hash"] = normalized["transaction_hash"].fillna("").astype(str)
    return normalized


def load_available_results(csv_paths: Sequence[Path]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load discovered experiment CSVs and return combined rows plus metadata."""
    result_frames: list[pd.DataFrame] = []
    available_rows: list[dict[str, object]] = []

    for csv_path in csv_paths:
        experiment_name = experiment_name_from_csv_path(csv_path)
        try:
            raw = pd.read_csv(csv_path)
            normalized = normalize_result_rows(raw)
            result_frames.append(normalized)
            available_rows.append(
                {
                    "experiment_name": experiment_name,
                    "csv_path": str(csv_path),
                    "included": True,
                    "row_count": len(normalized),
                }
            )
        except Exception as error:  # pragma: no cover - defensive metadata path
            available_rows.append(
                {
                    "experiment_name": experiment_name,
                    "csv_path": str(csv_path),
                    "included": False,
                    "row_count": 0,
                    "error": str(error),
                }
            )

    combined = (
        pd.concat(result_frames, ignore_index=True)
        if result_frames
        else pd.DataFrame(columns=COMMON_RESULT_COLUMNS)
    )
    available = pd.DataFrame(
        available_rows,
        columns=["experiment_name", "csv_path", "included", "row_count", "error"],
    ).fillna("")
    return combined, available


def create_summary(combined_results: pd.DataFrame) -> pd.DataFrame:
    """Create one summary row per variant."""
    combined_results = normalize_result_rows(combined_results)
    if combined_results.empty:
        return pd.DataFrame(
            columns=[
                "variant",
                "number_of_batches",
                "total_runtime_ms_sum",
                "total_runtime_ms_mean",
                "throughput_orders_per_second_mean",
                "correctness_pass_count",
                "correctness_fail_count",
                "gas_used_sum",
                "blockchain_time_ms_mean",
                "encryption_time_ms_mean",
                "decryption_time_ms_mean",
                "encrypted_computation_time_ms_mean",
                "ciphertext_size_bytes_mean",
            ]
        )

    rows: list[dict[str, object]] = []
    for variant, group in combined_results.groupby("variant", sort=True):
        correctness = group["correctness_pass"].astype(bool)
        rows.append(
            {
                "variant": variant,
                "number_of_batches": len(group),
                "total_runtime_ms_sum": group["total_runtime_ms"].sum(),
                "total_runtime_ms_mean": group["total_runtime_ms"].mean(),
                "total_runtime_s_sum": group["total_runtime_s"].sum(),
                "total_runtime_s_mean": group["total_runtime_s"].mean(),
                "throughput_orders_per_second_mean": group[
                    "throughput_orders_per_second"
                ].mean(),
                "correctness_pass_count": int(correctness.sum()),
                "correctness_fail_count": int((~correctness).sum()),
                "gas_used_sum": group["gas_used"].sum(),
                "blockchain_time_ms_mean": group["blockchain_time_ms"].mean(),
                "audit_overhead_s_mean": group["audit_overhead_s"].mean(),
                "audit_overhead_percent_mean": group["audit_overhead_percent"].mean(),
                "encryption_time_ms_mean": group["encryption_time_ms"].mean(),
                "decryption_time_ms_mean": group["decryption_time_ms"].mean(),
                "encrypted_computation_time_ms_mean": group[
                    "encrypted_computation_time_ms"
                ].mean(),
                "ciphertext_size_bytes_mean": group["ciphertext_size_bytes"].mean(),
            }
        )
    return pd.DataFrame(rows)


def run_final_comparison(
    results_root: str | Path = DEFAULT_RESULTS_ROOT,
    comparison_output_path: str | Path = DEFAULT_COMPARISON_PATH,
    summary_output_path: str | Path = DEFAULT_SUMMARY_PATH,
    available_output_path: str | Path = DEFAULT_AVAILABLE_EXPERIMENTS_PATH,
    figures_dir: str | Path = DEFAULT_FIGURES_DIR,
    show_progress: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[Path]]:
    """Generate final comparison CSVs and figures from discovered results."""
    csv_paths = discover_experiment_result_csvs(results_root)
    if show_progress:
        print_progress("Found experiment result files:")
        if csv_paths:
            for path in csv_paths:
                print_progress(f"- {experiment_name_from_csv_path(path)}")
        else:
            print_progress("- none")

    if show_progress:
        print_progress()
        print_progress("Combining result CSVs...")
    combined, available = load_available_results(csv_paths)
    summary = create_summary(combined)

    if show_progress:
        print_progress("Saving final comparison CSV...")
    save_dataframe(combined, comparison_output_path)
    save_dataframe(summary, summary_output_path)
    save_dataframe(available, available_output_path)

    figures_path = Path(figures_dir)
    figures_path.mkdir(parents=True, exist_ok=True)
    figure_paths: list[Path] = []
    if combined.empty:
        if show_progress:
            print_progress("No comparison rows found; skipping comparison graphs.")
    else:
        if show_progress:
            print_progress("Generating comparison graphs...")
        figure_paths = create_final_comparison_visualizations(combined, figures_path)
        if not ((combined["blockchain_time_ms"] > 0) | (combined["gas_used"] > 0)).any():
            print_progress("No blockchain rows found; skipping blockchain overhead graph.")
        if not (
            (combined["encryption_time_ms"] > 0)
            | (combined["decryption_time_ms"] > 0)
            | (combined["encrypted_computation_time_ms"] > 0)
        ).any():
            print_progress("No encryption rows found; skipping encryption overhead graph.")

    return combined, summary, available, figure_paths


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for final comparison generation."""
    parser = argparse.ArgumentParser(
        description="Generate final comparison CSVs and graphs from available experiment outputs."
    )
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_COMPARISON_PATH)
    parser.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument(
        "--available-output",
        type=Path,
        default=DEFAULT_AVAILABLE_EXPERIMENTS_PATH,
    )
    parser.add_argument("--figures-dir", type=Path, default=DEFAULT_FIGURES_DIR)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run final comparison generation from CLI arguments."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    print_progress("Running final comparison...")
    print_progress()
    run_final_comparison(
        results_root=args.results_root,
        comparison_output_path=args.output,
        summary_output_path=args.summary_output,
        available_output_path=args.available_output,
        figures_dir=args.figures_dir,
        show_progress=True,
    )
    print_progress()
    print_progress("Final comparison complete.")
    print_progress()
    print_progress("Outputs saved to:")
    print_progress(str(args.output.parent))
    print_progress(str(args.figures_dir))


if __name__ == "__main__":
    main()
