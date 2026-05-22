from pathlib import Path

import pandas as pd

from src.common.metrics import COMMON_RESULT_COLUMNS
from src.experiments.run_final_comparison import (
    create_summary,
    discover_experiment_result_csvs,
    normalize_result_rows,
    run_final_comparison,
)


def write_result_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def sample_plaintext_row(batch_id: str = "batch_0001") -> dict[str, object]:
    return {
        "variant": "plaintext",
        "batch_id": batch_id,
        "batch_size": 10,
        "buy_volume": 100,
        "sell_volume": 90,
        "matched_volume": 80,
        "executed_trade_count": 3,
        "correctness_pass": True,
        "total_runtime_ms": 5.0,
        "throughput_orders_per_second": 2000.0,
        "encryption_time_ms": 0,
        "encrypted_computation_time_ms": 0,
        "decryption_time_ms": 0,
        "ciphertext_size_bytes": 0,
        "blockchain_time_ms": 0,
        "gas_used": 0,
        "block_number": 0,
        "transaction_hash": "",
    }


def test_discovers_available_experiment_csvs_and_ignores_final_comparison(tmp_path: Path) -> None:
    baseline = tmp_path / "results/plaintext_baseline/csv/plaintext_baseline_results.csv"
    final = tmp_path / "results/final_comparison/csv/final_comparison_results.csv"
    write_result_csv(baseline, [sample_plaintext_row()])
    write_result_csv(final, [sample_plaintext_row()])

    discovered = discover_experiment_result_csvs(tmp_path / "results")

    assert discovered == [baseline]


def test_normalize_result_rows_adds_missing_common_columns() -> None:
    normalized = normalize_result_rows(
        pd.DataFrame(
            [
                {
                    "variant": "plaintext",
                    "batch_id": "batch_0001",
                    "batch_size": 10,
                    "correctness_pass": True,
                }
            ]
        )
    )

    assert normalized.columns[: len(COMMON_RESULT_COLUMNS)].tolist() == COMMON_RESULT_COLUMNS
    assert "total_runtime_s" in normalized.columns
    assert "audit_overhead_s" in normalized.columns
    assert normalized.iloc[0]["buy_volume"] == 0
    assert normalized.iloc[0]["blockchain_time_ms"] == 0
    assert normalized.iloc[0]["transaction_hash"] == ""
    assert bool(normalized.iloc[0]["correctness_pass"]) is True


def test_create_summary_returns_one_row_per_variant() -> None:
    rows = [
        sample_plaintext_row("batch_0001"),
        sample_plaintext_row("batch_0002"),
        {
            **sample_plaintext_row("batch_0001"),
            "variant": "plaintext_blockchain",
            "blockchain_time_ms": 3.0,
            "gas_used": 100000,
            "block_number": 2,
            "transaction_hash": "0xabc",
        },
    ]
    summary = create_summary(pd.DataFrame(rows))

    assert set(summary["variant"]) == {"plaintext", "plaintext_blockchain"}
    plaintext = summary[summary["variant"] == "plaintext"].iloc[0]
    blockchain = summary[summary["variant"] == "plaintext_blockchain"].iloc[0]
    assert plaintext["number_of_batches"] == 2
    assert plaintext["correctness_pass_count"] == 2
    assert blockchain["gas_used_sum"] == 100000
    assert blockchain["blockchain_time_ms_mean"] == 3.0
    assert blockchain["total_runtime_s_mean"] == 0.005


def test_run_final_comparison_writes_csvs_and_graphs(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    write_result_csv(
        results_root / "plaintext_baseline/csv/plaintext_baseline_results.csv",
        [sample_plaintext_row()],
    )
    write_result_csv(
        results_root / "plaintext_blockchain/csv/plaintext_blockchain_results.csv",
        [
            {
                **sample_plaintext_row(),
                "variant": "plaintext_blockchain",
                "blockchain_time_ms": 4.0,
                "gas_used": 120000,
                "block_number": 3,
                "transaction_hash": "0xabc",
            }
        ],
    )

    combined_path = results_root / "final_comparison/csv/final_comparison.csv"
    summary_path = results_root / "final_comparison/csv/final_comparison_summary.csv"
    available_path = results_root / "final_comparison/csv/available_experiments.csv"
    figures_dir = results_root / "final_comparison/figures"

    combined, summary, available, figures = run_final_comparison(
        results_root=results_root,
        comparison_output_path=combined_path,
        summary_output_path=summary_path,
        available_output_path=available_path,
        figures_dir=figures_dir,
    )

    assert combined_path.exists()
    assert summary_path.exists()
    assert available_path.exists()
    assert len(combined) == 2
    assert set(summary["variant"]) == {"plaintext", "plaintext_blockchain"}
    assert available["included"].tolist() == [True, True]
    assert (figures_dir / "runtime_by_variant_and_batch_size.png").exists()
    assert (figures_dir / "throughput_by_variant_and_batch_size.png").exists()
    assert (figures_dir / "correctness_by_variant.png").exists()
    assert (figures_dir / "blockchain_overhead_by_variant.png").exists()
    assert not (figures_dir / "encryption_overhead_by_variant.png").exists()
    assert len(figures) == 4


def test_run_final_comparison_skips_optional_graphs_without_matching_data(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    write_result_csv(
        results_root / "plaintext_baseline/csv/plaintext_baseline_results.csv",
        [sample_plaintext_row()],
    )

    run_final_comparison(
        results_root=results_root,
        comparison_output_path=results_root / "final_comparison/csv/final_comparison.csv",
        summary_output_path=results_root / "final_comparison/csv/final_comparison_summary.csv",
        available_output_path=results_root / "final_comparison/csv/available_experiments.csv",
        figures_dir=results_root / "final_comparison/figures",
    )

    figures_dir = results_root / "final_comparison/figures"
    assert (figures_dir / "runtime_by_variant_and_batch_size.png").exists()
    assert (figures_dir / "throughput_by_variant_and_batch_size.png").exists()
    assert (figures_dir / "correctness_by_variant.png").exists()
    assert not (figures_dir / "blockchain_overhead_by_variant.png").exists()
    assert not (figures_dir / "encryption_overhead_by_variant.png").exists()
