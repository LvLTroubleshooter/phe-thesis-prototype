"""Run the plaintext baseline experiment and save CSV results."""

from __future__ import annotations

import argparse
import contextlib
import gc
import io
from pathlib import Path
from statistics import fmean, median, stdev
from time import perf_counter
from typing import Sequence

import pandas as pd

from src.common.cleanup import clean_python_caches
from src.common.metrics import (
    append_dataframe,
    apply_common_result_schema,
    calculate_throughput,
    reset_output_file,
    save_dataframe,
    seconds_to_milliseconds,
)
from src.common.order_schema import validate_orders
from src.common.research_outputs import (
    RAW_RUN_COLUMNS,
    apply_wall_clock_runtime_columns,
    summarize_measured_runs,
    utc_now_iso,
    write_command_wall_clock_runtime,
    write_dataset_manifest,
    manifest_by_batch,
)
from src.common.synthetic_orders import (
    DEFAULT_SYNTHETIC_ORDERS_PATH,
    SyntheticOrderConfig,
    generate_and_save_synthetic_orders,
)
from src.common.timing import time_call
from src.variants.plaintext.baseline import (
    TRADE_LOG_COLUMNS,
    UNMATCHED_ORDER_COLUMNS,
    load_orders_csv,
    match_plaintext_clob_batch,
)
from src.visualization.visualize_plaintext_results import (
    DEFAULT_OUTPUT_DIR as DEFAULT_FIGURES_DIR,
)
from src.visualization.visualize_plaintext_results import create_plaintext_visualizations

DEFAULT_RESULTS_PATH = Path(
    "results/plaintext_baseline/csv/batch_summary.csv"
)
DEFAULT_RAW_RUNS_PATH = Path("results/plaintext_baseline/csv/raw_runs.csv")
DEFAULT_TRADES_PATH = Path("results/plaintext_baseline/csv/trades.csv")
DEFAULT_UNMATCHED_ORDERS_PATH = Path(
    "results/plaintext_baseline/csv/unmatched_orders.csv"
)
DEFAULT_EXPERIMENT_BATCH_SIZES = (
    10_000,
    25_000,
    50_000,
    100_000,
    250_000,
    500_000,
    1_000_000,
)
DEFAULT_WARMUP_RUNS = 5
DEFAULT_MEASURED_RUNS = 30
PLAINTEXT_VARIANT_NAME = "plaintext"


def print_progress(message: str = "") -> None:
    """Print simple terminal progress immediately."""
    print(message, flush=True)


def infer_results_root(output_path: Path) -> Path:
    """Infer the results root from an experiment CSV output path."""
    path = Path(output_path)
    if path.parent.name == "csv" and path.parent.parent.parent:
        return path.parent.parent.parent
    return Path("results")


def refresh_final_comparison(results_root: Path) -> None:
    """Regenerate final comparison outputs from current experiment results."""
    from src.experiments.generate_final_comparison import generate_final_comparison

    with contextlib.redirect_stdout(io.StringIO()):
        generate_final_comparison(results_root)


def load_or_generate_orders(
    input_path: Path,
    batch_sizes: tuple[int, ...] | None,
    seed: int,
    buy_ratio: float,
    min_quantity: int,
    max_quantity: int,
    min_price: float,
    max_price: float,
    symbol: str,
    trader_count: int,
) -> pd.DataFrame:
    """Load an existing dataset, or generate one when batch sizes are supplied."""
    if batch_sizes is not None:
        config = SyntheticOrderConfig(
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
        return generate_and_save_synthetic_orders(input_path, config)

    if input_path.exists():
        return load_orders_csv(input_path)

    return generate_and_save_synthetic_orders(input_path)


def calculate_runtime_stats(runtime_seconds: list[float]) -> dict[str, float]:
    """Calculate median, mean, and standard deviation for measured runtimes."""
    return {
        "median_runtime_seconds": median(runtime_seconds),
        "mean_runtime_seconds": fmean(runtime_seconds),
        "std_runtime_seconds": stdev(runtime_seconds)
        if len(runtime_seconds) > 1
        else 0.0,
    }


def run_plaintext_clob_experiment(
    orders: pd.DataFrame,
    warmup_runs: int = DEFAULT_WARMUP_RUNS,
    measured_runs: int = DEFAULT_MEASURED_RUNS,
    show_progress: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the plaintext CLOB baseline with repeated timing and outputs."""
    if warmup_runs < 0:
        raise ValueError("warmup_runs must be zero or greater")
    if measured_runs <= 0:
        raise ValueError("measured_runs must be greater than zero")

    validated_orders = validate_orders(orders)
    rows: list[dict[str, object]] = []
    trade_logs: list[pd.DataFrame] = []
    unmatched_outputs: list[pd.DataFrame] = []

    for _, batch_orders in validated_orders.groupby("batch_id", sort=True):
        batch_id = batch_orders["batch_id"].iloc[0]
        batch_size = len(batch_orders)
        batch_started_at = perf_counter()
        if show_progress:
            print_progress(f"Processing {batch_id} | batch size: {batch_size}")

        for _ in range(warmup_runs):
            match_plaintext_clob_batch(batch_orders)

        last_measured_result = None
        last_measured_trades = None
        last_measured_unmatched = None
        measured_runtimes = []
        for _ in range(measured_runs):
            clob_output, runtime_seconds = time_call(
                lambda batch_orders=batch_orders: match_plaintext_clob_batch(
                    batch_orders
                )
            )
            baseline_result, trades, unmatched_orders = clob_output
            last_measured_result = baseline_result
            last_measured_trades = trades
            last_measured_unmatched = unmatched_orders
            measured_runtimes.append(runtime_seconds)

        if (
            last_measured_result is None
            or last_measured_trades is None
            or last_measured_unmatched is None
        ):
            raise RuntimeError("No measured CLOB output was produced")

        baseline_result = last_measured_result
        trade_logs.append(last_measured_trades)
        unmatched_outputs.append(last_measured_unmatched)
        runtime_stats = calculate_runtime_stats(measured_runtimes)
        n_orders = int(baseline_result["n_orders"])
        median_runtime_seconds = runtime_stats["median_runtime_seconds"]
        median_runtime_ms = seconds_to_milliseconds(median_runtime_seconds)
        throughput = calculate_throughput(n_orders, median_runtime_seconds)

        rows.append(
            {
                "experiment_name": "plaintext_baseline",
                "variant": PLAINTEXT_VARIANT_NAME,
                "batch_id": baseline_result["batch_id"],
                "batch_size": n_orders,
                "buy_volume": baseline_result["buy_volume"],
                "sell_volume": baseline_result["sell_volume"],
                "matched_volume": baseline_result["matched_volume"],
                "executed_trade_count": baseline_result["executed_trade_count"],
                "correctness_pass": True,
                "total_runtime_ms": median_runtime_ms,
                "total_runtime_s": median_runtime_seconds,
                "throughput_orders_per_second": throughput,
                "encryption_time_ms": 0.0,
                "encrypted_computation_time_ms": 0.0,
                "decryption_time_ms": 0.0,
                "ciphertext_size_bytes": 0,
                "blockchain_time_ms": 0.0,
                "gas_used": 0,
                "block_number": 0,
                "transaction_hash": "",
                "warmup_runs": warmup_runs,
                "measured_runs": measured_runs,
                "input_orders_count": n_orders,
                "buy_orders_count": baseline_result["buy_order_count"],
                "sell_orders_count": baseline_result["sell_order_count"],
                "matched_trades_count": baseline_result["executed_trade_count"],
                "unmatched_orders_count": len(last_measured_unmatched),
                "matching_runtime_s_mean": runtime_stats["mean_runtime_seconds"],
                "matching_runtime_s_median": median_runtime_seconds,
                "evidence_write_runtime_s_mean": 0.0,
                "hashing_runtime_s_mean": 0.0,
                "blockchain_runtime_s_mean": 0.0,
                "total_runtime_s_mean": median_runtime_seconds,
                "total_runtime_s_median": median_runtime_seconds,
                "audit_overhead_s": 0.0,
                "audit_overhead_percent": 0.0,
                "blockchain_tx_count": 0,
                "blockchain_gas_used_total": 0,
                "input_hash": "",
                "trades_hash": "",
                "unmatched_hash": "",
                "matching_runtime_s": median_runtime_seconds,
                "evidence_write_runtime_s": 0.0,
                "hashing_runtime_s": 0.0,
                "blockchain_runtime_s": 0.0,
            }
        )
        if show_progress:
            batch_runtime_seconds = perf_counter() - batch_started_at
            print_progress(
                f"Completed {batch_id} | batch size: {batch_size} | "
                f"runtime: {batch_runtime_seconds:.2f} s"
            )

    results = apply_common_result_schema(pd.DataFrame(rows))
    trades = (
        pd.concat(trade_logs, ignore_index=True)
        if trade_logs
        else pd.DataFrame(columns=TRADE_LOG_COLUMNS)
    )
    unmatched_orders = (
        pd.concat(unmatched_outputs, ignore_index=True)
        if unmatched_outputs
        else pd.DataFrame(columns=UNMATCHED_ORDER_COLUMNS)
    )
    return results, trades, unmatched_orders


def run_plaintext_baseline_experiment(
    orders: pd.DataFrame,
    warmup_runs: int = DEFAULT_WARMUP_RUNS,
    measured_runs: int = DEFAULT_MEASURED_RUNS,
    show_progress: bool = False,
) -> pd.DataFrame:
    """Run the plaintext CLOB baseline and return only batch-level results."""
    results, _, _ = run_plaintext_clob_experiment(
        orders,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
        show_progress=show_progress,
    )
    return results


def run_experiment(
    input_path: Path = DEFAULT_SYNTHETIC_ORDERS_PATH,
    output_path: Path = DEFAULT_RESULTS_PATH,
    raw_runs_output_path: Path = DEFAULT_RAW_RUNS_PATH,
    trades_output_path: Path = DEFAULT_TRADES_PATH,
    unmatched_orders_output_path: Path = DEFAULT_UNMATCHED_ORDERS_PATH,
    batch_sizes: tuple[int, ...] | None = None,
    warmup_runs: int = DEFAULT_WARMUP_RUNS,
    measured_runs: int = DEFAULT_MEASURED_RUNS,
    show_progress: bool = False,
    seed: int = 42,
    buy_ratio: float = 0.5,
    min_quantity: int = 1,
    max_quantity: int = 1_000,
    min_price: float = 1_800.0,
    max_price: float = 2_200.0,
    symbol: str = "ETH-USD",
    trader_count: int = 25,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the plaintext CLOB experiment and save research-ready outputs."""
    experiment_started_at = perf_counter()
    if raw_runs_output_path == DEFAULT_RAW_RUNS_PATH and output_path != DEFAULT_RESULTS_PATH:
        raw_runs_output_path = Path(output_path).parent / "raw_runs.csv"
    orders, _data_loading_seconds = time_call(
        lambda: load_or_generate_orders(
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
    )
    validated_orders = validate_orders(orders)
    manifest = write_dataset_manifest(validated_orders, seed=seed)
    manifest_rows = manifest_by_batch(manifest)
    raw_rows: list[dict[str, object]] = []
    collect_return_logs = len(validated_orders) <= 100_000
    trade_logs: list[pd.DataFrame] = []
    unmatched_outputs: list[pd.DataFrame] = []
    reset_output_file(trades_output_path)
    reset_output_file(unmatched_orders_output_path)
    trade_header_pending = True
    unmatched_header_pending = True
    batch_wall_clock_runtime_s: dict[str, float] = {}

    for _, batch_orders in validated_orders.groupby("batch_id", sort=True):
        batch_started_at = perf_counter()
        batch_id = str(batch_orders["batch_id"].iloc[0])
        batch_size = int(len(batch_orders))
        batch_manifest = manifest_rows[batch_id]
        if show_progress:
            print_progress(f"Processing {batch_id} | batch size: {batch_size}")

        for warmup_index in range(warmup_runs):
            clob_output, runtime_seconds = time_call(
                lambda batch_orders=batch_orders: match_plaintext_clob_batch(batch_orders)
            )
            result, trades, unmatched_orders = clob_output
            raw_rows.append(
                build_plaintext_raw_run_row(
                    result=result,
                    trades=trades,
                    unmatched_orders=unmatched_orders,
                    run_id=f"warmup_{warmup_index + 1:04d}",
                    is_warmup=True,
                    seed=seed,
                    input_hash=str(batch_manifest["input_hash"]),
                    matching_runtime_s=runtime_seconds,
                )
            )
            del clob_output, result, trades, unmatched_orders
            gc.collect()

        for run_index in range(measured_runs):
            clob_output, runtime_seconds = time_call(
                lambda batch_orders=batch_orders: match_plaintext_clob_batch(batch_orders)
            )
            result, trades, unmatched_orders = clob_output
            raw_rows.append(
                build_plaintext_raw_run_row(
                    result=result,
                    trades=trades,
                    unmatched_orders=unmatched_orders,
                    run_id=f"measured_{run_index + 1:04d}",
                    is_warmup=False,
                    seed=seed,
                    input_hash=str(batch_manifest["input_hash"]),
                    matching_runtime_s=runtime_seconds,
                )
            )

            if run_index == 0:
                append_dataframe(
                    trades,
                    trades_output_path,
                    include_header=trade_header_pending,
                )
                append_dataframe(
                    unmatched_orders,
                    unmatched_orders_output_path,
                    include_header=unmatched_header_pending,
                )
                trade_header_pending = False
                unmatched_header_pending = False
                if collect_return_logs:
                    trade_logs.append(trades.copy())
                    unmatched_outputs.append(unmatched_orders.copy())

            del clob_output, result, trades, unmatched_orders
            gc.collect()

        batch_wall_clock_runtime_s[batch_id] = perf_counter() - batch_started_at
        gc.collect()

        if show_progress:
            print_progress(
                f"Completed {batch_id} | batch size: {batch_size} | "
                f"runtime: {batch_wall_clock_runtime_s[batch_id]:.2f} s"
            )

    raw_runs = pd.DataFrame(raw_rows, columns=RAW_RUN_COLUMNS)
    results = summarize_measured_runs(
        raw_runs,
        experiment_name="plaintext_baseline",
        variant=PLAINTEXT_VARIANT_NAME,
        seed=seed,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )
    if trade_header_pending:
        save_dataframe(pd.DataFrame(columns=TRADE_LOG_COLUMNS), trades_output_path)
    if unmatched_header_pending:
        save_dataframe(
            pd.DataFrame(columns=UNMATCHED_ORDER_COLUMNS),
            unmatched_orders_output_path,
        )
    trades = (
        pd.concat(trade_logs, ignore_index=True)
        if trade_logs
        else pd.DataFrame(columns=TRADE_LOG_COLUMNS)
    )
    unmatched_orders = (
        pd.concat(unmatched_outputs, ignore_index=True)
        if unmatched_outputs
        else pd.DataFrame(columns=UNMATCHED_ORDER_COLUMNS)
    )
    save_dataframe(raw_runs, raw_runs_output_path)
    results = apply_wall_clock_runtime_columns(
        results,
        batch_wall_clock_runtime_s=batch_wall_clock_runtime_s,
        experiment_wall_clock_runtime_s=perf_counter() - experiment_started_at,
    )
    save_dataframe(results, output_path)
    return results, trades, unmatched_orders


def build_plaintext_raw_run_row(
    result: dict[str, object],
    trades: pd.DataFrame,
    unmatched_orders: pd.DataFrame,
    run_id: str,
    is_warmup: bool,
    seed: int,
    input_hash: str,
    matching_runtime_s: float,
) -> dict[str, object]:
    """Build one plaintext baseline raw run row."""
    n_orders = int(result["n_orders"])
    throughput = calculate_throughput(n_orders, matching_runtime_s)
    matched_volume = int(result["matched_volume"])
    trade_volume = int(trades["executed_quantity"].sum()) if not trades.empty else 0
    return {
        "experiment_name": "plaintext_baseline",
        "variant": PLAINTEXT_VARIANT_NAME,
        "batch_id": result["batch_id"],
        "batch_size": n_orders,
        "run_id": run_id,
        "is_warmup": is_warmup,
        "seed": seed,
        "input_hash": input_hash,
        "matching_runtime_s": matching_runtime_s,
        "encryption_runtime_s": 0.0,
        "encrypted_computation_runtime_s": 0.0,
        "decryption_runtime_s": 0.0,
        "evidence_write_runtime_s": 0.0,
        "hashing_runtime_s": 0.0,
        "blockchain_runtime_s": 0.0,
        "total_runtime_s": matching_runtime_s,
        "throughput_orders_per_second": throughput,
        "matched_volume": matched_volume,
        "matched_trades_count": int(result["executed_trade_count"]),
        "unmatched_orders_count": len(unmatched_orders),
        "correctness_pass": matched_volume == trade_volume,
        "blockchain_tx_count": 0,
        "blockchain_gas_used_total": 0,
        "blockchain_block_number": 0,
        "blockchain_transaction_hash": "",
        "created_at": utc_now_iso(),
    }


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the plaintext baseline experiment."""
    parser = argparse.ArgumentParser(description="Run the plaintext baseline experiment.")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_SYNTHETIC_ORDERS_PATH,
        help="Input synthetic orders CSV path.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESULTS_PATH,
        help="Plaintext baseline batch summary CSV path.",
    )
    parser.add_argument(
        "--raw-runs-output",
        type=Path,
        default=DEFAULT_RAW_RUNS_PATH,
        help="Plaintext baseline raw runs CSV path.",
    )
    parser.add_argument(
        "--trades-output",
        type=Path,
        default=DEFAULT_TRADES_PATH,
        help="Plaintext CLOB trade log CSV path.",
    )
    parser.add_argument(
        "--unmatched-output",
        type=Path,
        default=DEFAULT_UNMATCHED_ORDERS_PATH,
        help="Plaintext CLOB unmatched orders CSV path.",
    )
    parser.add_argument(
        "--figures-dir",
        type=Path,
        default=DEFAULT_FIGURES_DIR,
        help="Directory for plaintext baseline graph outputs.",
    )
    parser.add_argument(
        "--skip-visualizations",
        action="store_true",
        help="Only write the result CSV; do not create graph outputs.",
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
        help="Generate fresh synthetic orders with these batch sizes before running.",
    )
    parser.add_argument("--warmup-runs", type=int, default=DEFAULT_WARMUP_RUNS)
    parser.add_argument("--measured-runs", type=int, default=DEFAULT_MEASURED_RUNS)
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
    """Run the plaintext baseline experiment from command-line arguments."""
    command_started_at = perf_counter()
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    batch_sizes = tuple(args.batch_sizes) if args.batch_sizes is not None else None

    try:
        results, trades, unmatched_orders = run_experiment(
            input_path=args.input,
            output_path=args.output,
            raw_runs_output_path=args.raw_runs_output,
            trades_output_path=args.trades_output,
            unmatched_orders_output_path=args.unmatched_output,
            batch_sizes=batch_sizes,
            warmup_runs=args.warmup_runs,
            measured_runs=args.measured_runs,
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
            create_plaintext_visualizations(
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
