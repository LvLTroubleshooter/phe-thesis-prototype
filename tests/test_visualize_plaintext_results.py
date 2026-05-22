import pandas as pd

from src.visualization.visualize_plaintext_results import create_plaintext_visualizations


def test_create_plaintext_visualizations_writes_graphs_without_html_table(tmp_path) -> None:
    input_path = tmp_path / "plaintext_results.csv"
    output_dir = tmp_path / "figures"
    pd.DataFrame(
        [
            {
                "variant": "plaintext",
                "batch_size": 10,
                "batch_id": "batch_0001",
                "n_orders": 10,
                "buy_order_count": 5,
                "sell_order_count": 5,
                "buy_volume": 100,
                "sell_volume": 80,
                "matched_volume": 80,
                "executed_trade_count": 1,
                "total_runtime_ms": 1.0,
                "throughput_orders_per_second": 10000.0,
                "correctness_pass": True,
            },
            {
                "variant": "plaintext",
                "batch_size": 20,
                "batch_id": "batch_0002",
                "n_orders": 20,
                "buy_order_count": 11,
                "sell_order_count": 9,
                "buy_volume": 150,
                "sell_volume": 160,
                "matched_volume": 150,
                "executed_trade_count": 2,
                "total_runtime_ms": 2.0,
                "throughput_orders_per_second": 10000.0,
                "correctness_pass": True,
            },
        ]
    ).to_csv(input_path, index=False)

    output_paths = create_plaintext_visualizations(input_path, output_dir)

    assert output_paths == [
        output_dir / "plaintext_baseline_volumes.png",
        output_dir / "plaintext_baseline_runtime.png",
        output_dir / "plaintext_baseline_throughput.png",
    ]
    assert all(output_path.exists() for output_path in output_paths)
    assert not (output_dir / "plaintext_baseline_table.html").exists()
