"""Shared order schema validation for prototype experiments."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

REQUIRED_ORDER_COLUMNS = (
    "order_id",
    "batch_id",
    "trader_id",
    "symbol",
    "side",
    "price",
    "quantity",
    "timestamp",
)

VALID_ORDER_SIDES = ("BUY", "SELL")


def validate_order_columns(orders: pd.DataFrame) -> None:
    """Ensure an order dataset contains the columns required by the prototype."""
    missing_columns = [
        column for column in REQUIRED_ORDER_COLUMNS if column not in orders.columns
    ]
    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise ValueError(f"Order dataset is missing required columns: {missing_text}")


def normalize_order_sides(orders: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with normalized uppercase order sides."""
    normalized = orders.copy()
    normalized["side"] = normalized["side"].astype(str).str.strip().str.upper()
    return normalized


def validate_order_sides(orders: pd.DataFrame) -> None:
    """Ensure every order side is one of the supported prototype values."""
    invalid_sides = sorted(
        side for side in orders["side"].dropna().unique() if side not in VALID_ORDER_SIDES
    )
    if invalid_sides:
        invalid_text = ", ".join(str(side) for side in invalid_sides)
        raise ValueError(f"Order dataset contains invalid side values: {invalid_text}")


def validate_order_quantities(orders: pd.DataFrame) -> None:
    """Ensure quantities are numeric and positive."""
    quantities = pd.to_numeric(orders["quantity"], errors="coerce")
    if quantities.isna().any():
        raise ValueError("Order dataset contains non-numeric quantity values")
    if (quantities <= 0).any():
        raise ValueError("Order dataset contains non-positive quantity values")


def validate_order_prices(orders: pd.DataFrame) -> None:
    """Ensure prices are numeric and positive."""
    prices = pd.to_numeric(orders["price"], errors="coerce")
    if prices.isna().any():
        raise ValueError("Order dataset contains non-numeric price values")
    if (prices <= 0).any():
        raise ValueError("Order dataset contains non-positive price values")


def validate_order_ids(orders: pd.DataFrame) -> None:
    """Ensure each order_id is unique within the dataset."""
    if orders["order_id"].duplicated().any():
        raise ValueError("Order dataset contains duplicate order_id values")


def validate_orders(orders: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize an order dataset for prototype variants."""
    validate_order_columns(orders)
    normalized = normalize_order_sides(orders)
    validate_order_sides(normalized)
    validate_order_quantities(normalized)
    validate_order_prices(normalized)
    validate_order_ids(normalized)

    result = normalized.copy()
    result["quantity"] = pd.to_numeric(result["quantity"], errors="raise")
    result["price"] = pd.to_numeric(result["price"], errors="raise")
    return result


def orders_from_records(records: Iterable[dict[str, object]]) -> pd.DataFrame:
    """Build a validated order DataFrame from dictionary records."""
    return validate_orders(pd.DataFrame.from_records(records))
