"""Paillier/PHE encrypted batch volume aggregation.

This variant is intentionally aggregate-only. It encrypts individual order
quantities, aggregates BUY and SELL quantities with Paillier ciphertext
addition, and decrypts only the final aggregate totals.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

import pandas as pd
from phe import paillier

from src.common.order_schema import validate_orders

PAILLIER_PHE_VARIANT = "paillier_phe"


@dataclass(frozen=True)
class PaillierEncryptedColumns:
    """Encrypted two-column representation for one order batch."""

    encrypted_buy_quantities: list[Any]
    encrypted_sell_quantities: list[Any]
    ciphertext_size_bytes: int


@dataclass(frozen=True)
class PaillierAggregationTimings:
    """Measured timings for one Paillier aggregate run."""

    encryption_runtime_s: float
    encrypted_computation_runtime_s: float
    decryption_runtime_s: float

    @property
    def total_runtime_s(self) -> float:
        return (
            self.encryption_runtime_s
            + self.encrypted_computation_runtime_s
            + self.decryption_runtime_s
        )


@dataclass(frozen=True)
class PaillierAggregationOutput:
    """Paillier aggregate result and timing evidence."""

    result: dict[str, object]
    timings: PaillierAggregationTimings
    ciphertext_size_bytes: int


def generate_paillier_keypair(
    n_length: int = 2048,
) -> tuple[paillier.PaillierPublicKey, paillier.PaillierPrivateKey]:
    """Generate a real Paillier public/private keypair."""
    return paillier.generate_paillier_keypair(n_length=n_length)


def plaintext_aggregate_reference(orders: pd.DataFrame) -> dict[str, object]:
    """Compute an independent plaintext aggregate reference for one batch."""
    validated = validate_one_batch(orders)
    batch_id = validated["batch_id"].iloc[0]
    buy_volume = int(validated.loc[validated["side"] == "BUY", "quantity"].sum())
    sell_volume = int(validated.loc[validated["side"] == "SELL", "quantity"].sum())
    return {
        "batch_id": batch_id,
        "n_orders": int(len(validated)),
        "buy_order_count": int((validated["side"] == "BUY").sum()),
        "sell_order_count": int((validated["side"] == "SELL").sum()),
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "matched_volume": min(buy_volume, sell_volume),
    }


def validate_one_batch(orders: pd.DataFrame) -> pd.DataFrame:
    """Validate orders and require exactly one batch ID."""
    validated = validate_orders(orders)
    batch_ids = validated["batch_id"].unique()
    if len(batch_ids) != 1:
        raise ValueError("Paillier aggregation expects exactly one batch_id")
    return validated


def encrypt_order_quantities(
    orders: pd.DataFrame,
    public_key: paillier.PaillierPublicKey,
) -> PaillierEncryptedColumns:
    """Encrypt order quantities into BUY and SELL ciphertext columns."""
    validated = validate_one_batch(orders)
    encrypted_buy_quantities: list[Any] = []
    encrypted_sell_quantities: list[Any] = []
    ciphertext_size_bytes = 0

    for order in validated.itertuples(index=False):
        quantity = int(order.quantity)
        if order.side == "BUY":
            encrypted_buy = public_key.encrypt(quantity)
            encrypted_sell = public_key.encrypt(0)
        elif order.side == "SELL":
            encrypted_buy = public_key.encrypt(0)
            encrypted_sell = public_key.encrypt(quantity)
        else:  # pragma: no cover - validate_orders rejects this earlier.
            raise ValueError(f"Unsupported order side: {order.side}")

        encrypted_buy_quantities.append(encrypted_buy)
        encrypted_sell_quantities.append(encrypted_sell)
        ciphertext_size_bytes += encrypted_number_size_bytes(encrypted_buy)
        ciphertext_size_bytes += encrypted_number_size_bytes(encrypted_sell)

    return PaillierEncryptedColumns(
        encrypted_buy_quantities=encrypted_buy_quantities,
        encrypted_sell_quantities=encrypted_sell_quantities,
        ciphertext_size_bytes=ciphertext_size_bytes,
    )


def aggregate_encrypted_columns(
    encrypted_columns: PaillierEncryptedColumns,
    public_key: paillier.PaillierPublicKey,
) -> tuple[Any, Any]:
    """Homomorphically sum encrypted BUY and SELL quantity columns."""
    encrypted_total_buy = public_key.encrypt(0)
    encrypted_total_sell = public_key.encrypt(0)

    for encrypted_buy in encrypted_columns.encrypted_buy_quantities:
        encrypted_total_buy += encrypted_buy
    for encrypted_sell in encrypted_columns.encrypted_sell_quantities:
        encrypted_total_sell += encrypted_sell

    return encrypted_total_buy, encrypted_total_sell


def decrypt_aggregate_totals(
    encrypted_total_buy: Any,
    encrypted_total_sell: Any,
    private_key: paillier.PaillierPrivateKey,
) -> tuple[int, int]:
    """Decrypt only final aggregate BUY and SELL totals."""
    buy_volume = int(private_key.decrypt(encrypted_total_buy))
    sell_volume = int(private_key.decrypt(encrypted_total_sell))
    return buy_volume, sell_volume


def run_paillier_batch_aggregation(
    orders: pd.DataFrame,
    public_key: paillier.PaillierPublicKey,
    private_key: paillier.PaillierPrivateKey,
) -> PaillierAggregationOutput:
    """Run timed Paillier encrypted aggregation for one validated batch."""
    validated = validate_one_batch(orders)
    reference = plaintext_aggregate_reference(validated)

    started_at = perf_counter()
    encrypted_columns = encrypt_order_quantities(validated, public_key)
    encryption_runtime_s = perf_counter() - started_at

    started_at = perf_counter()
    encrypted_total_buy, encrypted_total_sell = aggregate_encrypted_columns(
        encrypted_columns,
        public_key,
    )
    encrypted_computation_runtime_s = perf_counter() - started_at

    started_at = perf_counter()
    buy_volume, sell_volume = decrypt_aggregate_totals(
        encrypted_total_buy,
        encrypted_total_sell,
        private_key,
    )
    decryption_runtime_s = perf_counter() - started_at

    matched_volume = min(buy_volume, sell_volume)
    result = {
        "batch_id": reference["batch_id"],
        "n_orders": reference["n_orders"],
        "buy_order_count": reference["buy_order_count"],
        "sell_order_count": reference["sell_order_count"],
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "matched_volume": matched_volume,
        "reference_buy_volume": reference["buy_volume"],
        "reference_sell_volume": reference["sell_volume"],
        "reference_matched_volume": reference["matched_volume"],
        "correctness_pass": (
            buy_volume == reference["buy_volume"]
            and sell_volume == reference["sell_volume"]
            and matched_volume == reference["matched_volume"]
        ),
    }
    return PaillierAggregationOutput(
        result=result,
        timings=PaillierAggregationTimings(
            encryption_runtime_s=encryption_runtime_s,
            encrypted_computation_runtime_s=encrypted_computation_runtime_s,
            decryption_runtime_s=decryption_runtime_s,
        ),
        ciphertext_size_bytes=encrypted_columns.ciphertext_size_bytes,
    )


def encrypted_number_size_bytes(encrypted_number: Any) -> int:
    """Estimate serialized ciphertext integer size in bytes."""
    ciphertext = int(encrypted_number.ciphertext(be_secure=False))
    return max(1, (ciphertext.bit_length() + 7) // 8)
