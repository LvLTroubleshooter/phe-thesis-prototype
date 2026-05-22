"""Simplified plaintext Central Limit Order Book (CLOB) baseline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.common.order_schema import validate_orders

BASELINE_RESULT_COLUMNS = (
    "batch_id",
    "n_orders",
    "buy_order_count",
    "sell_order_count",
    "buy_volume",
    "sell_volume",
    "matched_volume",
    "unmatched_buy_volume",
    "unmatched_sell_volume",
    "executed_trade_count",
)

TRADE_LOG_COLUMNS = (
    "batch_id",
    "buy_order_id",
    "sell_order_id",
    "symbol",
    "execution_price",
    "executed_quantity",
    "execution_timestamp",
)

UNMATCHED_ORDER_COLUMNS = (
    "order_id",
    "batch_id",
    "trader_id",
    "symbol",
    "side",
    "price",
    "quantity",
    "remaining_quantity",
    "filled_quantity",
    "timestamp",
)


def _prepare_side_orders(orders: pd.DataFrame, side: str) -> list[dict[str, object]]:
    """Sort and prepare one side of the CLOB with remaining quantities."""
    side_orders = orders[orders["side"] == side].copy()
    ascending = [False, True] if side == "BUY" else [True, True]
    sorted_orders = side_orders.sort_values(
        ["price", "timestamp"],
        ascending=ascending,
        kind="mergesort",
    )
    records = sorted_orders.to_dict("records")
    for record in records:
        record["remaining_quantity"] = record["quantity"]
    return records


def _execution_timestamp(buy_order: dict[str, object], sell_order: dict[str, object]) -> str:
    """Return a deterministic execution timestamp for a matched pair."""
    return max(str(buy_order["timestamp"]), str(sell_order["timestamp"]))


def _unmatched_orders_from_books(
    buy_orders: list[dict[str, object]],
    sell_orders: list[dict[str, object]],
) -> pd.DataFrame:
    """Build an unmatched order DataFrame from remaining CLOB quantities."""
    rows: list[dict[str, object]] = []
    for order in buy_orders + sell_orders:
        remaining_quantity = order["remaining_quantity"]
        if remaining_quantity > 0:
            rows.append(
                {
                    "order_id": order["order_id"],
                    "batch_id": order["batch_id"],
                    "trader_id": order["trader_id"],
                    "symbol": order["symbol"],
                    "side": order["side"],
                    "price": order["price"],
                    "quantity": order["quantity"],
                    "remaining_quantity": remaining_quantity,
                    "filled_quantity": order["quantity"] - remaining_quantity,
                    "timestamp": order["timestamp"],
                }
            )
    return pd.DataFrame(rows, columns=UNMATCHED_ORDER_COLUMNS)


def match_plaintext_clob_batch(
    orders: pd.DataFrame,
) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    """Match one validated batch using a simplified Central Limit Order Book."""
    batch_ids = orders["batch_id"].unique()
    if len(batch_ids) != 1:
        raise ValueError("match_plaintext_clob_batch expects exactly one batch_id")

    batch_id = batch_ids[0]
    buy_orders = _prepare_side_orders(orders, "BUY")
    sell_orders = _prepare_side_orders(orders, "SELL")
    buy_volume = orders.loc[orders["side"] == "BUY", "quantity"].sum()
    sell_volume = orders.loc[orders["side"] == "SELL", "quantity"].sum()

    trades: list[dict[str, object]] = []
    buy_index = 0
    sell_index = 0

    while buy_index < len(buy_orders) and sell_index < len(sell_orders):
        buy_order = buy_orders[buy_index]
        sell_order = sell_orders[sell_index]

        if buy_order["price"] < sell_order["price"]:
            break

        executed_quantity = min(
            buy_order["remaining_quantity"],
            sell_order["remaining_quantity"],
        )
        trades.append(
            {
                "batch_id": batch_id,
                "buy_order_id": buy_order["order_id"],
                "sell_order_id": sell_order["order_id"],
                "symbol": buy_order["symbol"],
                "execution_price": sell_order["price"],
                "executed_quantity": executed_quantity,
                "execution_timestamp": _execution_timestamp(buy_order, sell_order),
            }
        )

        buy_order["remaining_quantity"] -= executed_quantity
        sell_order["remaining_quantity"] -= executed_quantity

        if buy_order["remaining_quantity"] == 0:
            buy_index += 1
        if sell_order["remaining_quantity"] == 0:
            sell_index += 1

    trade_log = pd.DataFrame(trades, columns=TRADE_LOG_COLUMNS)
    unmatched_orders = _unmatched_orders_from_books(buy_orders, sell_orders)
    matched_volume = (
        trade_log["executed_quantity"].sum() if not trade_log.empty else 0
    )

    result = {
        "batch_id": batch_id,
        "n_orders": int(len(orders)),
        "buy_order_count": int((orders["side"] == "BUY").sum()),
        "sell_order_count": int((orders["side"] == "SELL").sum()),
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "matched_volume": matched_volume,
        "unmatched_buy_volume": buy_volume - matched_volume,
        "unmatched_sell_volume": sell_volume - matched_volume,
        "executed_trade_count": int(len(trade_log)),
    }
    return result, trade_log, unmatched_orders


def aggregate_batch_orders(orders: pd.DataFrame) -> dict[str, object]:
    """Return only batch-level CLOB results for compatibility."""
    result, _, _ = match_plaintext_clob_batch(orders)
    return result


def aggregate_orders(orders: pd.DataFrame) -> pd.DataFrame:
    """Compute plaintext CLOB batch results for each batch."""
    validated_orders = validate_orders(orders)
    batch_results = [
        aggregate_batch_orders(batch_orders)
        for _, batch_orders in validated_orders.groupby("batch_id", sort=True)
    ]
    return pd.DataFrame(batch_results, columns=BASELINE_RESULT_COLUMNS)


def match_plaintext_clob_orders(
    orders: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Match all batches and return results, trades, and unmatched orders."""
    validated_orders = validate_orders(orders)
    result_rows = []
    trade_logs = []
    unmatched_rows = []

    for _, batch_orders in validated_orders.groupby("batch_id", sort=True):
        result, trades, unmatched = match_plaintext_clob_batch(batch_orders)
        result_rows.append(result)
        trade_logs.append(trades)
        unmatched_rows.append(unmatched)

    results = pd.DataFrame(result_rows, columns=BASELINE_RESULT_COLUMNS)
    trades = (
        pd.concat(trade_logs, ignore_index=True)
        if trade_logs
        else pd.DataFrame(columns=TRADE_LOG_COLUMNS)
    )
    unmatched = (
        pd.concat(unmatched_rows, ignore_index=True)
        if unmatched_rows
        else pd.DataFrame(columns=UNMATCHED_ORDER_COLUMNS)
    )
    return results, trades, unmatched


def load_orders_csv(input_path: str | Path) -> pd.DataFrame:
    """Load an order dataset from CSV and validate it."""
    return validate_orders(pd.read_csv(input_path))


def save_baseline_results(results: pd.DataFrame, output_path: str | Path) -> None:
    """Save plaintext baseline results to CSV."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(path, index=False)


def run_plaintext_baseline(input_path: str | Path, output_path: str | Path) -> pd.DataFrame:
    """Load orders, compute plaintext CLOB results, and save them."""
    orders = load_orders_csv(input_path)
    results, _, _ = match_plaintext_clob_orders(orders)
    save_baseline_results(results, output_path)
    return results
