"""Synthetic order generation for repeatable prototype experiments."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from random import Random
from typing import Sequence

import pandas as pd

from src.common.order_schema import validate_orders

DEFAULT_SYNTHETIC_ORDERS_PATH = Path("data/synthetic_orders.csv")


@dataclass(frozen=True)
class SyntheticOrderConfig:
    """Configuration for deterministic synthetic order generation."""

    batch_sizes: tuple[int, ...] = (10, 100, 1_000)
    seed: int = 42
    buy_ratio: float = 0.5
    min_quantity: int = 1
    max_quantity: int = 1_000
    min_price: float = 1_800.0
    max_price: float = 2_200.0
    symbol: str = "ETH-USD"
    trader_count: int = 25
    start_timestamp: datetime = datetime(2026, 1, 1, tzinfo=UTC)


DEFAULT_SYNTHETIC_ORDER_CONFIG = SyntheticOrderConfig()


def validate_synthetic_order_config(config: SyntheticOrderConfig) -> None:
    """Validate generator settings before creating a dataset."""
    if not config.batch_sizes:
        raise ValueError("At least one batch size is required")
    if any(batch_size <= 0 for batch_size in config.batch_sizes):
        raise ValueError("Batch sizes must be positive integers")
    if not 0 <= config.buy_ratio <= 1:
        raise ValueError("buy_ratio must be between 0 and 1")
    if config.min_quantity <= 0:
        raise ValueError("min_quantity must be greater than zero")
    if config.max_quantity < config.min_quantity:
        raise ValueError("max_quantity must be greater than or equal to min_quantity")
    if config.min_price <= 0:
        raise ValueError("min_price must be greater than zero")
    if config.max_price < config.min_price:
        raise ValueError("max_price must be greater than or equal to min_price")
    if config.trader_count <= 0:
        raise ValueError("trader_count must be greater than zero")
    if not config.symbol.strip():
        raise ValueError("symbol must not be empty")


def generate_synthetic_orders(config: SyntheticOrderConfig) -> pd.DataFrame:
    """Generate repeatable synthetic BUY and SELL orders."""
    validate_synthetic_order_config(config)
    rng = Random(config.seed)
    records: list[dict[str, object]] = []
    order_number = 1

    for batch_index, batch_size in enumerate(config.batch_sizes, start=1):
        batch_id = f"batch_{batch_index:04d}"

        for order_index in range(batch_size):
            side = "BUY" if rng.random() < config.buy_ratio else "SELL"
            quantity = rng.randint(config.min_quantity, config.max_quantity)
            price = round(rng.uniform(config.min_price, config.max_price), 2)
            trader_number = rng.randint(1, config.trader_count)
            timestamp = config.start_timestamp + timedelta(seconds=order_number - 1)

            records.append(
                {
                    "order_id": f"order_{order_number:08d}",
                    "batch_id": batch_id,
                    "trader_id": f"trader_{trader_number:04d}",
                    "symbol": config.symbol,
                    "side": side,
                    "price": price,
                    "quantity": quantity,
                    "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                }
            )
            order_number += 1

    return validate_orders(pd.DataFrame.from_records(records))


def save_synthetic_orders(orders: pd.DataFrame, output_path: str | Path) -> None:
    """Save a synthetic order dataset to CSV."""
    validated_orders = validate_orders(orders)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    validated_orders.to_csv(path, index=False)


def generate_and_save_synthetic_orders(
    output_path: str | Path = DEFAULT_SYNTHETIC_ORDERS_PATH,
    config: SyntheticOrderConfig = DEFAULT_SYNTHETIC_ORDER_CONFIG,
) -> pd.DataFrame:
    """Generate a repeatable synthetic dataset and save it to CSV."""
    orders = generate_synthetic_orders(config)
    save_synthetic_orders(orders, output_path)
    return orders


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for synthetic order generation."""
    parser = argparse.ArgumentParser(
        description="Generate repeatable synthetic order CSV data."
    )
    parser.add_argument(
        "--batch-sizes",
        type=int,
        nargs="+",
        default=DEFAULT_SYNTHETIC_ORDER_CONFIG.batch_sizes,
        help="One or more batch sizes, for example: --batch-sizes 50 500 5000",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SYNTHETIC_ORDER_CONFIG.seed,
        help="Random seed used to make generated orders repeatable.",
    )
    parser.add_argument(
        "--buy-ratio",
        type=float,
        default=DEFAULT_SYNTHETIC_ORDER_CONFIG.buy_ratio,
        help="Probability that each generated order is a BUY order.",
    )
    parser.add_argument(
        "--min-quantity",
        type=int,
        default=DEFAULT_SYNTHETIC_ORDER_CONFIG.min_quantity,
        help="Minimum generated order quantity.",
    )
    parser.add_argument(
        "--max-quantity",
        type=int,
        default=DEFAULT_SYNTHETIC_ORDER_CONFIG.max_quantity,
        help="Maximum generated order quantity.",
    )
    parser.add_argument(
        "--min-price",
        type=float,
        default=DEFAULT_SYNTHETIC_ORDER_CONFIG.min_price,
        help="Minimum generated limit price.",
    )
    parser.add_argument(
        "--max-price",
        type=float,
        default=DEFAULT_SYNTHETIC_ORDER_CONFIG.max_price,
        help="Maximum generated limit price.",
    )
    parser.add_argument(
        "--symbol",
        default=DEFAULT_SYNTHETIC_ORDER_CONFIG.symbol,
        help="Symbol or asset pair to use in generated orders.",
    )
    parser.add_argument(
        "--trader-count",
        type=int,
        default=DEFAULT_SYNTHETIC_ORDER_CONFIG.trader_count,
        help="Number of synthetic traders to sample from.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SYNTHETIC_ORDERS_PATH,
        help="CSV output path for generated orders.",
    )
    return parser


def config_from_args(args: argparse.Namespace) -> SyntheticOrderConfig:
    """Create generator configuration from parsed command-line arguments."""
    return SyntheticOrderConfig(
        batch_sizes=tuple(args.batch_sizes),
        seed=args.seed,
        buy_ratio=args.buy_ratio,
        min_quantity=args.min_quantity,
        max_quantity=args.max_quantity,
        min_price=args.min_price,
        max_price=args.max_price,
        symbol=args.symbol,
        trader_count=args.trader_count,
    )


def main(argv: Sequence[str] | None = None) -> None:
    """Generate a raw synthetic order dataset from command-line options."""
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    config = config_from_args(args)
    orders = generate_and_save_synthetic_orders(args.output, config)
    batch_sizes_text = ", ".join(str(batch_size) for batch_size in config.batch_sizes)
    print(
        f"Generated {len(orders)} synthetic orders across batch sizes "
        f"{batch_sizes_text} at {args.output}"
    )


if __name__ == "__main__":
    main()
