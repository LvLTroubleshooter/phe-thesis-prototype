import pandas as pd

from src.common.synthetic_orders import SyntheticOrderConfig, generate_synthetic_orders
from src.experiments.run_plaintext_baseline import (
    DEFAULT_EXPERIMENT_BATCH_SIZES,
    main,
    run_experiment,
    run_plaintext_clob_experiment,
    run_plaintext_baseline_experiment,
)


def test_run_plaintext_baseline_experiment_adds_metrics() -> None:
    orders = generate_synthetic_orders(SyntheticOrderConfig(batch_sizes=(3, 5), seed=1))

    results = run_plaintext_baseline_experiment(
        orders,
        warmup_runs=1,
        measured_runs=3,
    )

    assert results["batch_size"].tolist() == [3, 5]
    assert results["variant"].unique().tolist() == ["plaintext"]
    assert results["correctness_pass"].tolist() == [True, True]
    assert (results["total_runtime_ms"] >= 0).all()
    assert (results["throughput_orders_per_second"] > 0).all()
    assert "executed_trade_count" in results.columns


def test_run_plaintext_clob_experiment_returns_trades_and_unmatched() -> None:
    orders = generate_synthetic_orders(SyntheticOrderConfig(batch_sizes=(8,), seed=2))

    results, trades, unmatched = run_plaintext_clob_experiment(
        orders,
        warmup_runs=1,
        measured_runs=2,
    )

    assert int(results.iloc[0]["matched_volume"]) == int(
        trades["executed_quantity"].sum()
    )
    assert set(unmatched["side"]).issubset({"BUY", "SELL"})


def test_run_experiment_writes_one_plaintext_result_file(tmp_path) -> None:
    input_path = tmp_path / "synthetic_orders.csv"
    output_path = tmp_path / "plaintext_results.csv"
    trades_output_path = tmp_path / "plaintext_trades.csv"
    unmatched_output_path = tmp_path / "plaintext_unmatched.csv"

    results, trades, unmatched = run_experiment(
        input_path=input_path,
        output_path=output_path,
        trades_output_path=trades_output_path,
        unmatched_orders_output_path=unmatched_output_path,
        batch_sizes=(4, 6),
        warmup_runs=1,
        measured_runs=3,
        seed=5,
    )

    assert input_path.exists()
    assert output_path.exists()
    assert trades_output_path.exists()
    assert unmatched_output_path.exists()
    saved_results = pd.read_csv(output_path)
    assert results["batch_size"].tolist() == [4, 6]
    assert int(results["batch_size"].sum()) == 10
    assert "variant" in saved_results.columns
    assert "correctness_pass" in saved_results.columns
    assert saved_results["variant"].unique().tolist() == ["plaintext"]
    assert saved_results["correctness_pass"].tolist() == [True, True]
    assert "total_runtime_s_mean" in saved_results.columns
    assert "matching_runtime_s_mean" in saved_results.columns
    assert "audit_overhead_s_mean" in saved_results.columns
    assert saved_results["total_runtime_s_mean"].gt(0).all()
    assert saved_results["audit_overhead_s_mean"].tolist() == [0.0, 0.0]
    assert int(saved_results["matched_volume"].sum()) == int(
        trades["executed_quantity"].sum()
    )
    assert set(unmatched.columns).issuperset({"order_id", "remaining_quantity"})


def test_main_writes_results_visualizations_and_progress(tmp_path, capsys) -> None:
    input_path = tmp_path / "synthetic_orders.csv"
    output_path = tmp_path / "results/plaintext_baseline/csv/plaintext_results.csv"
    trades_output_path = tmp_path / "results/plaintext_baseline/csv/plaintext_trades.csv"
    unmatched_output_path = (
        tmp_path / "results/plaintext_baseline/csv/plaintext_unmatched.csv"
    )
    figures_dir = tmp_path / "results/plaintext_baseline/figures"

    main(
        [
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--trades-output",
            str(trades_output_path),
            "--unmatched-output",
            str(unmatched_output_path),
            "--figures-dir",
            str(figures_dir),
            "--batch-sizes",
            "3",
            "5",
            "--warmup-runs",
            "1",
            "--measured-runs",
            "3",
            "--seed",
            "10",
        ]
    )

    assert input_path.exists()
    assert output_path.parent.exists()
    assert figures_dir.exists()
    assert output_path.exists()
    assert trades_output_path.exists()
    assert unmatched_output_path.exists()
    assert (figures_dir / "plaintext_baseline_volumes.png").exists()
    assert (figures_dir / "plaintext_baseline_runtime.png").exists()
    assert (figures_dir / "plaintext_baseline_throughput.png").exists()
    assert not (figures_dir / "plaintext_baseline_table.html").exists()
    output = capsys.readouterr().out
    assert "Processing batch_0001 | batch size: 3" in output
    assert "Completed batch_0001 | batch size: 3 | runtime:" in output
    assert "Processing batch_0002 | batch size: 5" in output
    assert "Completed batch_0002 | batch size: 5 | runtime:" in output
    assert "median runtime:" not in output
    assert "Results saved to:" not in output
    assert "Trade log saved to:" not in output
    assert "Unmatched orders saved to:" not in output
    assert "Figures saved to:" not in output


def test_default_experiment_batch_sizes_match_dissertation_plan() -> None:
    assert DEFAULT_EXPERIMENT_BATCH_SIZES == (
        10_000,
        25_000,
        50_000,
        100_000,
        250_000,
        500_000,
        1_000_000,
    )
