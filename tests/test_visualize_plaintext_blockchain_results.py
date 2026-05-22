from pathlib import Path

import pandas as pd

from src.visualization.visualize_plaintext_blockchain_results import (
    create_plaintext_blockchain_visualizations,
)


def test_create_plaintext_blockchain_visualizations(tmp_path: Path) -> None:
    input_path = tmp_path / "plaintext_blockchain_results.csv"
    output_dir = tmp_path / "figures"
    pd.DataFrame(
        [
            {
                "variant": "plaintext_blockchain",
                "batch_id": "batch_0001",
                "batch_size": 100,
                "buy_volume": 5000,
                "sell_volume": 4000,
                "matched_volume": 3500,
                "executed_trade_count": 20,
                "correctness_pass": True,
                "total_runtime_ms": 8.0,
                "throughput_orders_per_second": 12500.0,
                "blockchain_time_ms": 3.4,
                "gas_used": 100000,
                "block_number": 10,
                "transaction_hash": "0xabc",
            }
        ]
    ).to_csv(input_path, index=False)

    output_paths = create_plaintext_blockchain_visualizations(input_path, output_dir)

    assert output_paths == [
        output_dir / "plaintext_blockchain_gas_used.png",
        output_dir / "plaintext_blockchain_transaction_time.png",
        output_dir / "plaintext_blockchain_blocks.png",
    ]
    for output_path in output_paths:
        assert output_path.exists()
    assert not (output_dir / "plaintext_blockchain_table.html").exists()
