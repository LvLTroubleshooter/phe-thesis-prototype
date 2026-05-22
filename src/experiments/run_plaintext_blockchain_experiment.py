"""Run the plaintext CLOB blockchain audit experiment."""

from __future__ import annotations

import argparse
import contextlib
import io
from pathlib import Path
from time import perf_counter
from typing import Sequence

from src.common.cleanup import clean_python_caches
from src.common.research_outputs import write_command_wall_clock_runtime
from src.variants.blockchain.plaintext_blockchain_runner import (
    DEFAULT_BLOCKCHAIN_RESULTS_PATH,
    DEFAULT_BLOCKCHAIN_RAW_RUNS_PATH,
    DEFAULT_BLOCKCHAIN_AUDIT_PATH,
    DEFAULT_BLOCKCHAIN_TRADES_PATH,
    DEFAULT_BLOCKCHAIN_UNMATCHED_ORDERS_PATH,
    DEFAULT_DEPLOYMENT_PATH,
    DEFAULT_ORDERS_PATH,
    DEFAULT_EXPERIMENT_BATCH_SIZES,
    DEFAULT_MEASURED_RUNS,
    DEFAULT_WARMUP_RUNS,
    DEFAULT_CONFIRMATIONS,
    DEFAULT_SUBMISSION_MODE,
    SUBMISSION_MODES,
    run_plaintext_blockchain_audit,
)
from src.visualization.visualize_plaintext_blockchain_results import (
    DEFAULT_OUTPUT_DIR as DEFAULT_FIGURES_DIR,
)
from src.visualization.visualize_plaintext_blockchain_results import (
    create_plaintext_blockchain_visualizations,
)


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


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for the plaintext blockchain experiment."""
    parser = argparse.ArgumentParser(
        description="Run the plaintext CLOB blockchain audit experiment."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_ORDERS_PATH)
    parser.add_argument("--trades-output", type=Path, default=DEFAULT_BLOCKCHAIN_TRADES_PATH)
    parser.add_argument("--unmatched-output", type=Path, default=DEFAULT_BLOCKCHAIN_UNMATCHED_ORDERS_PATH)
    parser.add_argument("--deployment", type=Path, default=DEFAULT_DEPLOYMENT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_BLOCKCHAIN_RESULTS_PATH)
    parser.add_argument("--raw-runs-output", type=Path, default=DEFAULT_BLOCKCHAIN_RAW_RUNS_PATH)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_BLOCKCHAIN_AUDIT_PATH)
    parser.add_argument("--figures-dir", type=Path, default=DEFAULT_FIGURES_DIR)
    parser.add_argument("--rpc-url", default=None)
    parser.add_argument("--confirmations", type=int, default=DEFAULT_CONFIRMATIONS)
    parser.add_argument(
        "--submission-mode",
        choices=sorted(SUBMISSION_MODES),
        default=DEFAULT_SUBMISSION_MODE,
    )
    parser.add_argument("--batch-sizes", type=int, nargs="+", default=DEFAULT_EXPERIMENT_BATCH_SIZES)
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
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run the plaintext blockchain audit experiment from CLI arguments."""
    command_started_at = perf_counter()
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    batch_sizes = tuple(args.batch_sizes) if args.batch_sizes is not None else None

    try:
        results, trades, unmatched_orders = run_plaintext_blockchain_audit(
            input_path=args.input,
            trades_output_path=args.trades_output,
            unmatched_orders_output_path=args.unmatched_output,
            deployment_path=args.deployment,
            output_path=args.output,
            raw_runs_output_path=args.raw_runs_output,
            blockchain_audit_output_path=args.audit_output,
            batch_sizes=batch_sizes,
            warmup_runs=args.warmup_runs,
            measured_runs=args.measured_runs,
            rpc_url=args.rpc_url,
            show_progress=True,
            seed=args.seed,
            buy_ratio=args.buy_ratio,
            min_quantity=args.min_quantity,
            max_quantity=args.max_quantity,
            min_price=args.min_price,
            max_price=args.max_price,
            symbol=args.symbol,
            trader_count=args.trader_count,
            confirmations=args.confirmations,
            submission_mode=args.submission_mode,
        )

        if not args.skip_visualizations:
            create_plaintext_blockchain_visualizations(
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
