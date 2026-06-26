"""Run the Paillier/PHE encrypted batch volume aggregation experiment."""

from __future__ import annotations

import argparse
import contextlib
import gc
import io
from pathlib import Path
from time import perf_counter
from typing import Sequence

import pandas as pd

from src.common.cleanup import clean_python_caches
from src.common.metrics import calculate_throughput, save_dataframe
from src.common.order_schema import validate_orders
from src.common.research_outputs import (
    RAW_RUN_COLUMNS,
    apply_wall_clock_runtime_columns,
    manifest_by_batch,
    summarize_measured_runs,
    utc_now_iso,
    write_command_wall_clock_runtime,
    write_dataset_manifest,
)
from src.common.synthetic_orders import DEFAULT_SYNTHETIC_ORDERS_PATH
from src.experiments.run_plaintext_baseline import (
    infer_results_root,
    load_or_generate_orders,
)
from src.variants.paillier_phe.aggregation import (
    PAILLIER_PHE_VARIANT,
    generate_paillier_keypair,
    run_paillier_batch_aggregation,
)
from src.visualization.visualize_paillier_phe_results import (
    DEFAULT_OUTPUT_DIR as DEFAULT_FIGURES_DIR,
)
from src.visualization.visualize_paillier_phe_results import (
    create_paillier_phe_visualizations,
)

DEFAULT_RESULTS_PATH = Path("results/paillier_phe/csv/batch_summary.csv")
DEFAULT_RAW_RUNS_PATH = Path("results/paillier_phe/csv/raw_runs.csv")
DEFAULT_BATCH_EVIDENCE_DIR = Path("results/paillier_phe/batch_evidence")
DEFAULT_EXPERIMENT_BATCH_SIZES = (100, 500, 1_000)
DEFAULT_WARMUP_RUNS = 1
DEFAULT_MEASURED_RUNS = 5
DEFAULT_KEY_SIZE_BITS = 2048


def print_progress(message: str = "") -> None:
    """Print simple terminal progress immediately."""
    print(message, flush=True)


def refresh_final_comparison(results_root: Path) -> None:
    """Regenerate final comparison outputs from current experiment results."""
    from src.experiments.generate_final_comparison import generate_final_comparison

    with contextlib.redirect_stdout(io.StringIO()):
        generate_final_comparison(results_root)


def run_paillier_phe_experiment(
    input_path: Path = DEFAULT_SYNTHETIC_ORDERS_PATH,
    output_path: Path = DEFAULT_RESULTS_PATH,
    raw_runs_output_path: Path = DEFAULT_RAW_RUNS_PATH,
    batch_evidence_dir: Path = DEFAULT_BATCH_EVIDENCE_DIR,
    batch_sizes: tuple[int, ...] | None = DEFAULT_EXPERIMENT_BATCH_SIZES,
    warmup_runs: int = DEFAULT_WARMUP_RUNS,
    measured_runs: int = DEFAULT_MEASURED_RUNS,
    key_size_bits: int = DEFAULT_KEY_SIZE_BITS,
    show_progress: bool = False,
    seed: int = 42,
    buy_ratio: float = 0.5,
    min_quantity: int = 1,
    max_quantity: int = 1_000,
    min_price: float = 1_800.0,
    max_price: float = 2_200.0,
    symbol: str = "ETH-USD",
    trader_count: int = 25,
) -> pd.DataFrame:
    """Run Stage 7 and save research-ready Paillier/PHE outputs."""
    if warmup_runs < 0:
        raise ValueError("warmup_runs must be zero or greater")
    if measured_runs <= 0:
        raise ValueError("measured_runs must be greater than zero")
    if key_size_bits < 128:
        raise ValueError("key_size_bits must be at least 128")
    if raw_runs_output_path == DEFAULT_RAW_RUNS_PATH and output_path != DEFAULT_RESULTS_PATH:
        raw_runs_output_path = Path(output_path).parent / "raw_runs.csv"
    if batch_evidence_dir == DEFAULT_BATCH_EVIDENCE_DIR and output_path != DEFAULT_RESULTS_PATH:
        batch_evidence_dir = Path(output_path).parent.parent / "batch_evidence"

    experiment_started_at = perf_counter()
    orders = load_or_generate_orders(
        input_path=input_path,
        batch_sizes=batch_sizes,
        seed=seed,
        buy_ratio=buy_ratio,
        min_quantity=min_quantity,
        max_quantity=max_quantity,
        min_price=min_price,
        max_price=max_price,
        symbol=symbol,
        trader_count=trader_count,
    )
    validated_orders = validate_orders(orders)
    manifest = write_dataset_manifest(validated_orders, seed=seed)
    manifest_rows = manifest_by_batch(manifest)
    public_key, private_key = generate_paillier_keypair(n_length=key_size_bits)

    raw_rows: list[dict[str, object]] = []
    batch_wall_clock_runtime_s: dict[str, float] = {}

    for _, batch_orders in validated_orders.groupby("batch_id", sort=True):
        batch_started_at = perf_counter()
        batch_id = str(batch_orders["batch_id"].iloc[0])
        batch_size = int(len(batch_orders))
        batch_manifest = manifest_rows[batch_id]
        if show_progress:
            print_progress(f"Processing {batch_id} | batch size: {batch_size}")

        for warmup_index in range(warmup_runs):
            output = run_paillier_batch_aggregation(
                batch_orders,
                public_key,
                private_key,
            )
            raw_rows.append(
                build_paillier_raw_run_row(
                    output=output,
                    run_id=f"warmup_{warmup_index + 1:04d}",
                    is_warmup=True,
                    seed=seed,
                    input_hash=str(batch_manifest["input_hash"]),
                )
            )
            del output
            gc.collect()

        for run_index in range(measured_runs):
            output = run_paillier_batch_aggregation(
                batch_orders,
                public_key,
                private_key,
            )
            evidence_write_runtime_s = 0.0
            if run_index == 0:
                evidence_started_at = perf_counter()
                write_paillier_batch_evidence(
                    batch_orders=batch_orders,
                    output=output,
                    batch_evidence_dir=batch_evidence_dir,
                )
                evidence_write_runtime_s = perf_counter() - evidence_started_at
            raw_rows.append(
                build_paillier_raw_run_row(
                    output=output,
                    run_id=f"measured_{run_index + 1:04d}",
                    is_warmup=False,
                    seed=seed,
                    input_hash=str(batch_manifest["input_hash"]),
                    evidence_write_runtime_s=evidence_write_runtime_s,
                )
            )
            del output
            gc.collect()

        batch_wall_clock_runtime_s[batch_id] = perf_counter() - batch_started_at
        if show_progress:
            print_progress(
                f"Completed {batch_id} | batch size: {batch_size} | "
                f"runtime: {batch_wall_clock_runtime_s[batch_id]:.2f} s"
            )

    raw_runs = pd.DataFrame(raw_rows, columns=RAW_RUN_COLUMNS)
    results = summarize_measured_runs(
        raw_runs,
        experiment_name=PAILLIER_PHE_VARIANT,
        variant=PAILLIER_PHE_VARIANT,
        seed=seed,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )
    save_dataframe(raw_runs, raw_runs_output_path)
    results = apply_wall_clock_runtime_columns(
        results,
        batch_wall_clock_runtime_s=batch_wall_clock_runtime_s,
        experiment_wall_clock_runtime_s=perf_counter() - experiment_started_at,
    )
    save_dataframe(results, output_path)
    return results


def build_paillier_raw_run_row(
    output: object,
    run_id: str,
    is_warmup: bool,
    seed: int,
    input_hash: str,
    evidence_write_runtime_s: float = 0.0,
) -> dict[str, object]:
    """Build one Paillier/PHE raw run row."""
    result = output.result
    timings = output.timings
    n_orders = int(result["n_orders"])
    total_runtime_s = timings.total_runtime_s + evidence_write_runtime_s
    return {
        "experiment_name": PAILLIER_PHE_VARIANT,
        "variant": PAILLIER_PHE_VARIANT,
        "batch_id": result["batch_id"],
        "batch_size": n_orders,
        "run_id": run_id,
        "is_warmup": is_warmup,
        "seed": seed,
        "input_hash": input_hash,
        "ciphertext_size_bytes": int(output.ciphertext_size_bytes),
        "matching_runtime_s": 0.0,
        "encryption_runtime_s": timings.encryption_runtime_s,
        "encrypted_computation_runtime_s": timings.encrypted_computation_runtime_s,
        "decryption_runtime_s": timings.decryption_runtime_s,
        "evidence_write_runtime_s": evidence_write_runtime_s,
        "hashing_runtime_s": 0.0,
        "blockchain_runtime_s": 0.0,
        "total_runtime_s": total_runtime_s,
        "throughput_orders_per_second": calculate_throughput(n_orders, total_runtime_s),
        "matched_volume": int(result["matched_volume"]),
        "matched_trades_count": 0,
        "unmatched_orders_count": 0,
        "correctness_pass": bool(result["correctness_pass"]),
        "blockchain_tx_count": 0,
        "blockchain_gas_used_total": 0,
        "blockchain_block_number": 0,
        "blockchain_transaction_hash": "",
        "created_at": utc_now_iso(),
    }


def write_paillier_batch_evidence(
    batch_orders: pd.DataFrame,
    output: object,
    batch_evidence_dir: Path,
) -> tuple[Path, Path]:
    """Write one batch's input and aggregate evidence files."""
    result = output.result
    timings = output.timings
    batch_id = str(result["batch_id"])
    orders_path = batch_evidence_dir / f"{batch_id}_orders.csv"
    aggregate_path = batch_evidence_dir / f"{batch_id}_paillier_aggregate.csv"

    save_dataframe(validate_orders(batch_orders), orders_path)
    save_dataframe(
        pd.DataFrame(
            [
                {
                    "experiment_name": PAILLIER_PHE_VARIANT,
                    "variant": PAILLIER_PHE_VARIANT,
                    "batch_id": batch_id,
                    "batch_size": int(result["n_orders"]),
                    "buy_volume": int(result["buy_volume"]),
                    "sell_volume": int(result["sell_volume"]),
                    "matched_volume": int(result["matched_volume"]),
                    "reference_buy_volume": int(result["reference_buy_volume"]),
                    "reference_sell_volume": int(result["reference_sell_volume"]),
                    "reference_matched_volume": int(
                        result["reference_matched_volume"]
                    ),
                    "correctness_pass": bool(result["correctness_pass"]),
                    "ciphertext_size_bytes": int(output.ciphertext_size_bytes),
                    "encryption_runtime_s": timings.encryption_runtime_s,
                    "encrypted_computation_runtime_s": (
                        timings.encrypted_computation_runtime_s
                    ),
                    "decryption_runtime_s": timings.decryption_runtime_s,
                    "created_at": utc_now_iso(),
                }
            ]
        ),
        aggregate_path,
    )
    return orders_path, aggregate_path


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the Paillier/PHE experiment."""
    parser = argparse.ArgumentParser(
        description="Run the Paillier/PHE encrypted batch volume aggregation experiment."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_SYNTHETIC_ORDERS_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument(
        "--raw-runs-output",
        type=Path,
        default=DEFAULT_RAW_RUNS_PATH,
    )
    parser.add_argument(
        "--batch-evidence-dir",
        type=Path,
        default=DEFAULT_BATCH_EVIDENCE_DIR,
    )
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=DEFAULT_FIGURES_DIR,
    )
    parser.add_argument(
        "--skip-visualizations",
        action="store_true",
        help="Only write CSV outputs; do not create graph outputs.",
    )
    parser.add_argument(
        "--skip-cache-cleanup",
        action="store_true",
        help="Keep generated Python __pycache__ folders after the run.",
    )
    parser.add_argument(
        "--skip-final-comparison",
        action="store_true",
        help="Do not refresh results/final_comparison after the experiment.",
    )
    parser.add_argument(
        "--batch-sizes",
        type=int,
        nargs="+",
        default=DEFAULT_EXPERIMENT_BATCH_SIZES,
    )
    parser.add_argument("--warmup-runs", type=int, default=DEFAULT_WARMUP_RUNS)
    parser.add_argument("--measured-runs", type=int, default=DEFAULT_MEASURED_RUNS)
    parser.add_argument("--key-size-bits", type=int, default=DEFAULT_KEY_SIZE_BITS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--buy-ratio", type=float, default=0.5)
    parser.add_argument("--min-quantity", type=int, default=1)
    parser.add_argument("--max-quantity", type=int, default=1_000)
    parser.add_argument("--min-price", type=float, default=1_800.0)
    parser.add_argument("--max-price", type=float, default=2_200.0)
    parser.add_argument("--symbol", default="ETH-USD")
    parser.add_argument("--trader-count", type=int, default=25)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the Paillier/PHE experiment from command-line arguments."""
    command_started_at = perf_counter()
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    batch_sizes = tuple(args.batch_sizes) if args.batch_sizes is not None else None

    try:
        run_paillier_phe_experiment(
            input_path=args.input,
            output_path=args.output,
            raw_runs_output_path=args.raw_runs_output,
            batch_evidence_dir=args.batch_evidence_dir,
            batch_sizes=batch_sizes,
            warmup_runs=args.warmup_runs,
            measured_runs=args.measured_runs,
            key_size_bits=args.key_size_bits,
            show_progress=True,
            seed=args.seed,
            buy_ratio=args.buy_ratio,
            min_quantity=args.min_quantity,
            max_quantity=args.max_quantity,
            min_price=args.min_price,
            max_price=args.max_price,
            symbol=args.symbol,
            trader_count=args.trader_count,
        )

        if not args.skip_visualizations:
            create_paillier_phe_visualizations(
                input_path=args.output,
                output_dir=args.figures_dir,
            )

        if not args.skip_final_comparison:
            refresh_final_comparison(infer_results_root(args.output))
    finally:
        if not args.skip_cache_cleanup:
            clean_python_caches()
        command_wall_clock_runtime_s = perf_counter() - command_started_at
        write_command_wall_clock_runtime(args.output, command_wall_clock_runtime_s)


if __name__ == "__main__":
    main()
