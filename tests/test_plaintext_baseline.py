import pandas as pd
import pytest

from src.common.order_schema import orders_from_records
from src.variants.plaintext.baseline import (
    aggregate_orders,
    match_plaintext_clob_orders,
)


def _order(
    order_id: str,
    side: str,
    price: float,
    quantity: int,
    timestamp: str,
    batch_id: str = "b1",
) -> dict[str, object]:
    return {
        "order_id": order_id,
        "batch_id": batch_id,
        "trader_id": f"trader_{order_id}",
        "symbol": "ETH-USD",
        "side": side,
        "price": price,
        "quantity": quantity,
        "timestamp": timestamp,
    }


def test_clob_matches_when_buy_price_crosses_sell_price() -> None:
    orders = orders_from_records(
        [
            _order("buy1", "BUY", 2_000, 10, "2026-01-01T00:00:00Z"),
            _order("sell1", "SELL", 1_990, 7, "2026-01-01T00:00:01Z"),
        ]
    )

    results, trades, unmatched = match_plaintext_clob_orders(orders)

    row = results.iloc[0]
    assert row["buy_volume"] == 10
    assert row["sell_volume"] == 7
    assert row["matched_volume"] == 7
    assert row["unmatched_buy_volume"] == 3
    assert row["unmatched_sell_volume"] == 0
    assert row["executed_trade_count"] == 1
    assert trades["executed_quantity"].sum() == row["matched_volume"]
    assert trades.iloc[0]["buy_order_id"] == "buy1"
    assert trades.iloc[0]["sell_order_id"] == "sell1"
    assert unmatched.iloc[0]["order_id"] == "buy1"
    assert unmatched.iloc[0]["remaining_quantity"] == 3


def test_clob_does_not_match_when_buy_price_is_below_sell_price() -> None:
    orders = orders_from_records(
        [
            _order("buy1", "BUY", 1_980, 10, "2026-01-01T00:00:00Z"),
            _order("sell1", "SELL", 1_990, 7, "2026-01-01T00:00:01Z"),
        ]
    )

    results, trades, unmatched = match_plaintext_clob_orders(orders)

    row = results.iloc[0]
    assert row["matched_volume"] == 0
    assert row["unmatched_buy_volume"] == 10
    assert row["unmatched_sell_volume"] == 7
    assert row["executed_trade_count"] == 0
    assert trades.empty
    assert sorted(unmatched["order_id"].tolist()) == ["buy1", "sell1"]


def test_clob_uses_price_time_priority_and_partial_fills() -> None:
    orders = orders_from_records(
        [
            _order("buy_low", "BUY", 2_000, 10, "2026-01-01T00:00:00Z"),
            _order("buy_high", "BUY", 2_010, 5, "2026-01-01T00:00:01Z"),
            _order("sell_early", "SELL", 1_990, 8, "2026-01-01T00:00:02Z"),
            _order("sell_late", "SELL", 1_990, 20, "2026-01-01T00:00:03Z"),
        ]
    )

    results, trades, unmatched = match_plaintext_clob_orders(orders)

    assert trades["buy_order_id"].tolist() == ["buy_high", "buy_low", "buy_low"]
    assert trades["sell_order_id"].tolist() == [
        "sell_early",
        "sell_early",
        "sell_late",
    ]
    assert trades["executed_quantity"].tolist() == [5, 3, 7]
    assert int(results.iloc[0]["matched_volume"]) == 15
    assert int(trades["executed_quantity"].sum()) == 15
    remaining_sell = unmatched[unmatched["order_id"] == "sell_late"].iloc[0]
    assert remaining_sell["remaining_quantity"] == 13


def test_aggregate_orders_returns_clob_batch_results() -> None:
    orders = pd.DataFrame(
        [
            _order("o1", "buy", 2_000, 4, "2026-01-01T00:00:00Z", "b1"),
            _order("o2", "sell", 2_100, 9, "2026-01-01T00:00:01Z", "b2"),
        ]
    )

    results = aggregate_orders(orders)

    assert results["batch_id"].tolist() == ["b1", "b2"]
    assert results["buy_volume"].tolist() == [4, 0]
    assert results["sell_volume"].tolist() == [0, 9]
    assert results["matched_volume"].tolist() == [0, 0]
    assert results["executed_trade_count"].tolist() == [0, 0]


def test_orders_require_price() -> None:
    order = _order("o1", "BUY", 2_000, 4, "2026-01-01T00:00:00Z")
    order.pop("price")

    with pytest.raises(ValueError, match="price"):
        aggregate_orders(pd.DataFrame([order]))


def test_orders_reject_duplicate_order_id() -> None:
    orders = pd.DataFrame(
        [
            _order("o1", "BUY", 2_000, 4, "2026-01-01T00:00:00Z"),
            _order("o1", "SELL", 1_990, 4, "2026-01-01T00:00:01Z"),
        ]
    )

    with pytest.raises(ValueError, match="duplicate order_id"):
        aggregate_orders(orders)


def test_aggregate_orders_rejects_invalid_side() -> None:
    orders = pd.DataFrame(
        [_order("o1", "HOLD", 2_000, 4, "2026-01-01T00:00:00Z")]
    )

    with pytest.raises(ValueError, match="invalid side"):
        aggregate_orders(orders)
