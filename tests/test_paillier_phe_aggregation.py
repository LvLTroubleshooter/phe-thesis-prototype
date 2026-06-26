import pandas as pd
import pytest

from src.variants.paillier_phe.aggregation import (
    aggregate_encrypted_columns,
    decrypt_aggregate_totals,
    encrypt_order_quantities,
    generate_paillier_keypair,
    plaintext_aggregate_reference,
    run_paillier_batch_aggregation,
)


def sample_orders() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "order_id": "order_00000001",
                "batch_id": "batch_0001",
                "trader_id": "trader_0001",
                "symbol": "ETH-USD",
                "side": "BUY",
                "price": 2000.0,
                "quantity": 7,
                "timestamp": "2026-01-01T00:00:00Z",
            },
            {
                "order_id": "order_00000002",
                "batch_id": "batch_0001",
                "trader_id": "trader_0002",
                "symbol": "ETH-USD",
                "side": "SELL",
                "price": 1990.0,
                "quantity": 4,
                "timestamp": "2026-01-01T00:00:01Z",
            },
            {
                "order_id": "order_00000003",
                "batch_id": "batch_0001",
                "trader_id": "trader_0003",
                "symbol": "ETH-USD",
                "side": "BUY",
                "price": 1980.0,
                "quantity": 5,
                "timestamp": "2026-01-01T00:00:02Z",
            },
        ]
    )


class CountingPrivateKey:
    def __init__(self, wrapped):
        self.wrapped = wrapped
        self.decrypt_calls = 0

    def decrypt(self, encrypted_number):
        self.decrypt_calls += 1
        return self.wrapped.decrypt(encrypted_number)


def test_plaintext_aggregate_reference_uses_min_buy_sell_volume() -> None:
    reference = plaintext_aggregate_reference(sample_orders())

    assert reference["buy_volume"] == 12
    assert reference["sell_volume"] == 4
    assert reference["matched_volume"] == 4


def test_paillier_aggregation_encrypts_individual_quantities_and_decrypts_only_totals() -> None:
    public_key, private_key = generate_paillier_keypair(n_length=128)
    counting_private_key = CountingPrivateKey(private_key)

    encrypted_columns = encrypt_order_quantities(sample_orders(), public_key)
    encrypted_total_buy, encrypted_total_sell = aggregate_encrypted_columns(
        encrypted_columns,
        public_key,
    )
    buy_volume, sell_volume = decrypt_aggregate_totals(
        encrypted_total_buy,
        encrypted_total_sell,
        counting_private_key,
    )

    assert buy_volume == 12
    assert sell_volume == 4
    assert counting_private_key.decrypt_calls == 2
    assert encrypted_columns.ciphertext_size_bytes > 0


def test_run_paillier_batch_aggregation_matches_plaintext_reference() -> None:
    public_key, private_key = generate_paillier_keypair(n_length=128)

    output = run_paillier_batch_aggregation(sample_orders(), public_key, private_key)

    assert output.result["buy_volume"] == 12
    assert output.result["sell_volume"] == 4
    assert output.result["matched_volume"] == 4
    assert output.result["correctness_pass"] is True
    assert output.timings.encryption_runtime_s >= 0
    assert output.timings.encrypted_computation_runtime_s >= 0
    assert output.timings.decryption_runtime_s >= 0
    assert output.ciphertext_size_bytes > 0


def test_paillier_aggregation_rejects_multiple_batches() -> None:
    orders = sample_orders()
    orders.loc[0, "batch_id"] = "batch_9999"
    public_key, private_key = generate_paillier_keypair(n_length=128)

    with pytest.raises(ValueError, match="exactly one batch_id"):
        run_paillier_batch_aggregation(orders, public_key, private_key)
