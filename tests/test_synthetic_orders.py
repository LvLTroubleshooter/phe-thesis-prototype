import pandas as pd
import pytest

from src.common.order_schema import REQUIRED_ORDER_COLUMNS
from src.common.synthetic_orders import (
    SyntheticOrderConfig,
    build_argument_parser,
    config_from_args,
    generate_and_save_synthetic_orders,
    generate_synthetic_orders,
    main,
)
from src.variants.plaintext.baseline import aggregate_orders


def test_generate_synthetic_orders_is_repeatable_with_same_seed() -> None:
    config = SyntheticOrderConfig(batch_sizes=(5, 3), seed=123)

    first = generate_synthetic_orders(config)
    second = generate_synthetic_orders(config)

    pd.testing.assert_frame_equal(first, second)


def test_generate_synthetic_orders_uses_expected_schema_and_batch_sizes() -> None:
    config = SyntheticOrderConfig(
        batch_sizes=(4, 6),
        seed=7,
        buy_ratio=0.75,
        min_quantity=10,
        max_quantity=20,
        min_price=1_800,
        max_price=1_900,
        symbol="BTC-USD",
    )

    orders = generate_synthetic_orders(config)

    assert list(orders.columns) == list(REQUIRED_ORDER_COLUMNS)
    assert len(orders) == 10
    assert orders.groupby("batch_id").size().to_dict() == {
        "batch_0001": 4,
        "batch_0002": 6,
    }
    assert set(orders["side"]).issubset({"BUY", "SELL"})
    assert orders["quantity"].between(10, 20).all()
    assert orders["price"].between(1_800, 1_900).all()
    assert orders["symbol"].unique().tolist() == ["BTC-USD"]


def test_generated_orders_work_with_plaintext_baseline() -> None:
    orders = generate_synthetic_orders(
        SyntheticOrderConfig(batch_sizes=(20,), seed=99, min_quantity=1, max_quantity=5)
    )

    results = aggregate_orders(orders)
    row = results.iloc[0]

    assert row["n_orders"] == 20
    assert row["buy_order_count"] + row["sell_order_count"] == 20
    assert row["matched_volume"] <= min(row["buy_volume"], row["sell_volume"])
    assert row["unmatched_buy_volume"] == row["buy_volume"] - row["matched_volume"]
    assert row["unmatched_sell_volume"] == row["sell_volume"] - row["matched_volume"]


def test_generate_and_save_synthetic_orders_writes_csv(tmp_path) -> None:
    output_path = tmp_path / "synthetic_orders.csv"
    config = SyntheticOrderConfig(batch_sizes=(2,), seed=5)

    generated = generate_and_save_synthetic_orders(output_path, config)
    loaded = pd.read_csv(output_path)

    assert output_path.exists()
    assert len(generated) == 2
    assert len(loaded) == 2
    assert list(loaded.columns) == list(REQUIRED_ORDER_COLUMNS)


def test_generate_synthetic_orders_rejects_invalid_config() -> None:
    config = SyntheticOrderConfig(batch_sizes=(0,))

    with pytest.raises(ValueError, match="positive integers"):
        generate_synthetic_orders(config)


def test_config_from_args_supports_dynamic_batch_sizes() -> None:
    parser = build_argument_parser()

    args = parser.parse_args(
        [
            "--batch-sizes",
            "3",
            "7",
            "11",
            "--seed",
            "123",
            "--buy-ratio",
            "0.25",
            "--min-price",
            "1800",
            "--max-price",
            "1900",
        ]
    )
    config = config_from_args(args)

    assert config.batch_sizes == (3, 7, 11)
    assert config.seed == 123
    assert config.buy_ratio == 0.25
    assert config.min_price == 1800
    assert config.max_price == 1900


def test_main_writes_dynamic_batch_size_dataset(tmp_path) -> None:
    output_path = tmp_path / "dynamic_orders.csv"

    main(
        [
            "--batch-sizes",
            "2",
            "4",
            "--seed",
            "12",
            "--output",
            str(output_path),
        ]
    )
    loaded = pd.read_csv(output_path)

    assert len(loaded) == 6
    assert loaded.groupby("batch_id").size().to_dict() == {
        "batch_0001": 2,
        "batch_0002": 4,
    }
