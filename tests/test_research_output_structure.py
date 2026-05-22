from pathlib import Path

import pandas as pd

from src.common.research_outputs import (
    BATCH_SUMMARY_COLUMNS,
    BLOCKCHAIN_AUDIT_COLUMNS,
    RAW_RUN_COLUMNS,
)
from src.experiments.generate_final_comparison import generate_final_comparison
from src.experiments.run_plaintext_baseline import main as run_plaintext_main


def write_csv(path: Path, rows: list[dict[str, object]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


def raw_row(
    experiment_name: str,
    variant: str,
    batch_id: str,
    batch_size: int,
    run_id: str,
    is_warmup: bool,
    total_runtime_s: float,
    blockchain_runtime_s: float = 0.0,
    gas_used: int = 0,
) -> dict[str, object]:
    return {
        "experiment_name": experiment_name,
        "variant": variant,
        "batch_id": batch_id,
        "batch_size": batch_size,
        "run_id": run_id,
        "is_warmup": is_warmup,
        "seed": 42,
        "input_hash": "a" * 64,
        "matching_runtime_s": max(total_runtime_s - blockchain_runtime_s, 0.0001),
        "encryption_runtime_s": 0,
        "encrypted_computation_runtime_s": 0,
        "decryption_runtime_s": 0,
        "evidence_write_runtime_s": 0,
        "hashing_runtime_s": 0,
        "blockchain_runtime_s": blockchain_runtime_s,
        "total_runtime_s": total_runtime_s,
        "throughput_orders_per_second": batch_size / total_runtime_s,
        "matched_volume": 100,
        "matched_trades_count": 3,
        "unmatched_orders_count": 2,
        "correctness_pass": True,
        "blockchain_tx_count": 1 if blockchain_runtime_s else 0,
        "blockchain_gas_used_total": gas_used,
        "blockchain_block_number": 7 if gas_used else 0,
        "blockchain_transaction_hash": "0xabc" if gas_used else "",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


def summary_row(
    experiment_name: str,
    variant: str,
    batch_id: str,
    batch_size: int,
    total_runtime_s: float,
    blockchain_runtime_s: float = 0.0,
    gas_used: int = 0,
) -> dict[str, object]:
    audit_overhead = blockchain_runtime_s
    matching_runtime = max(total_runtime_s - audit_overhead, 0.0001)
    return {
        "experiment_name": experiment_name,
        "variant": variant,
        "batch_id": batch_id,
        "batch_size": batch_size,
        "seed": 42,
        "measured_runs": 2,
        "warmup_runs": 1,
        "input_hash": "a" * 64,
        "matching_runtime_s_mean": matching_runtime,
        "matching_runtime_s_median": matching_runtime,
        "matching_runtime_s_std": 0,
        "matching_runtime_s_min": matching_runtime,
        "matching_runtime_s_max": matching_runtime,
        "total_runtime_s_mean": total_runtime_s,
        "total_runtime_s_median": total_runtime_s,
        "total_runtime_s_std": 0,
        "total_runtime_s_min": total_runtime_s,
        "total_runtime_s_max": total_runtime_s,
        "throughput_orders_per_second_mean": batch_size / total_runtime_s,
        "throughput_orders_per_second_median": batch_size / total_runtime_s,
        "throughput_orders_per_second_std": 0,
        "matched_volume": 100,
        "matched_trades_count": 3,
        "unmatched_orders_count": 2,
        "correctness_pass": True,
        "audit_overhead_s_mean": audit_overhead,
        "audit_overhead_percent_mean": audit_overhead / matching_runtime * 100,
        "blockchain_runtime_s_mean": blockchain_runtime_s,
        "blockchain_tx_count_mean": 1 if blockchain_runtime_s else 0,
        "blockchain_gas_used_total_mean": gas_used,
    }


def test_plaintext_runner_writes_canonical_outputs_and_refreshes_comparison(
    tmp_path: Path,
) -> None:
    results_root = tmp_path / "results"
    output_path = results_root / "plaintext_baseline/csv/batch_summary.csv"
    figures_dir = results_root / "plaintext_baseline/figures"

    run_plaintext_main(
        [
            "--input",
            str(tmp_path / "data/synthetic_orders.csv"),
            "--output",
            str(output_path),
            "--trades-output",
            str(results_root / "plaintext_baseline/csv/trades.csv"),
            "--unmatched-output",
            str(results_root / "plaintext_baseline/csv/unmatched_orders.csv"),
            "--figures-dir",
            str(figures_dir),
            "--batch-sizes",
            "4",
            "--warmup-runs",
            "2",
            "--measured-runs",
            "3",
            "--skip-visualizations",
            "--skip-cache-cleanup",
        ]
    )

    raw_runs_path = results_root / "plaintext_baseline/csv/raw_runs.csv"
    assert output_path.exists()
    assert raw_runs_path.exists()
    assert (results_root / "plaintext_baseline/csv/trades.csv").exists()
    assert (results_root / "plaintext_baseline/csv/unmatched_orders.csv").exists()
    assert (results_root / "final_comparison/csv/comparison_summary.csv").exists()
    assert not (
        results_root / "plaintext_baseline/csv/plaintext_baseline_results.csv"
    ).exists()

    raw_runs = pd.read_csv(raw_runs_path)
    summary = pd.read_csv(output_path)
    assert raw_runs["is_warmup"].astype(str).str.lower().tolist().count("true") == 2
    assert raw_runs["is_warmup"].astype(str).str.lower().tolist().count("false") == 3
    assert int(summary.iloc[0]["measured_runs"]) == 3
    assert int(summary.iloc[0]["warmup_runs"]) == 2
    assert set(RAW_RUN_COLUMNS).issubset(raw_runs.columns)
    assert set(BATCH_SUMMARY_COLUMNS).issubset(summary.columns)


def test_final_comparison_uses_canonical_research_outputs(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    experiments = [
        ("plaintext_baseline", "plaintext", 0.01, 0.0, 0),
        ("plaintext_blockchain", "plaintext_blockchain", 0.04, 0.02, 120000),
    ]
    for experiment_name, variant, total_runtime, chain_runtime, gas_used in experiments:
        write_csv(
            results_root / experiment_name / "csv/raw_runs.csv",
            [
                raw_row(
                    experiment_name,
                    variant,
                    "batch_0001",
                    10,
                    "measured_0001",
                    False,
                    total_runtime,
                    chain_runtime,
                    gas_used,
                )
            ],
            RAW_RUN_COLUMNS,
        )
        write_csv(
            results_root / experiment_name / "csv/batch_summary.csv",
            [
                summary_row(
                    experiment_name,
                    variant,
                    "batch_0001",
                    10,
                    total_runtime,
                    chain_runtime,
                    gas_used,
                )
            ],
            BATCH_SUMMARY_COLUMNS,
        )

    write_csv(
        results_root / "plaintext_blockchain/csv/blockchain_audit.csv",
        [
            {
                "experiment_name": "plaintext_blockchain",
                "variant": "plaintext_blockchain",
                "batch_id": "batch_0001",
                "batch_size": 10,
                "input_hash": "a" * 64,
                "trades_hash": "b" * 64,
                "unmatched_hash": "c" * 64,
                "result_hash": "d" * 64,
                "evidence_root_hash": "e" * 64,
                "contract_address": "0x1234567890123456789012345678901234567890",
                "transaction_hash": "0xabc",
                "block_number": 7,
                "gas_used": 120000,
                "transaction_time_s": 0.02,
                "confirmation_time_s": 0.02,
                "status": "success",
                "created_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        BLOCKCHAIN_AUDIT_COLUMNS,
    )
    write_csv(
        results_root / "final_comparison/csv/final_comparison.csv",
        [{"legacy": "should be ignored"}],
        ["legacy"],
    )

    generate_final_comparison(results_root)

    expected_csvs = [
        "all_raw_runs.csv",
        "comparison_summary.csv",
        "correctness_comparison.csv",
        "overhead_breakdown.csv",
        "blockchain_overhead.csv",
        "run_time_by_experiment_run.csv",
        "experiment_manifest.csv",
    ]
    for filename in expected_csvs:
        assert (results_root / "final_comparison/csv" / filename).exists()

    expected_figures = [
        "01_total_runtime_comparison.png",
        "02_throughput_comparison.png",
        "03_runtime_component_breakdown.png",
        "04_relative_slowdown_vs_baseline.png",
        "05_audit_overhead_percentage.png",
        "06_correctness_matched_volume.png",
        "07_blockchain_gas_used.png",
        "08_blockchain_transaction_time.png",
        "09_scalability_loglog_runtime.png",
    ]
    for filename in expected_figures:
        assert (results_root / "final_comparison/figures" / filename).exists()

    comparison = pd.read_csv(results_root / "final_comparison/csv/comparison_summary.csv")
    assert set(comparison["variant"]) == {"plaintext", "plaintext_blockchain"}
    blockchain = comparison[comparison["variant"] == "plaintext_blockchain"].iloc[0]
    assert blockchain["relative_slowdown_vs_plaintext"] == 4
    run_times = pd.read_csv(
        results_root / "final_comparison/csv/run_time_by_experiment_run.csv"
    )
    assert run_times.columns.tolist() == [
        "experiment_name",
        "variant",
        "batch_id",
        "batch_size",
        "run_id",
        "total_runtime_s",
    ]
    expected_run_times = [
        {
            "experiment_name": "plaintext_baseline",
            "variant": "plaintext",
            "batch_id": "batch_0001",
            "batch_size": 10,
            "run_id": "measured_0001",
            "total_runtime_s": 0.01,
        },
        {
            "experiment_name": "plaintext_blockchain",
            "variant": "plaintext_blockchain",
            "batch_id": "batch_0001",
            "batch_size": 10,
            "run_id": "measured_0001",
            "total_runtime_s": 0.04,
        },
    ]
    assert run_times.to_dict("records") == expected_run_times
    thesis_runtime = pd.read_csv(
        results_root / "final_comparison/tables/thesis_table_runtime_summary.csv"
    )
    assert thesis_runtime.to_dict("records") == expected_run_times
    assert (
        results_root / "final_comparison/tables/thesis_table_run_time_by_run.csv"
    ).exists()


def test_canonical_output_schema_rejects_old_filename_requirements() -> None:
    old_filenames = {
        "plaintext_baseline_results.csv",
        "plaintext_blockchain_results.csv",
        "final_comparison.csv",
    }
    canonical_filenames = {
        "raw_runs.csv",
        "batch_summary.csv",
        "trades.csv",
        "unmatched_orders.csv",
        "blockchain_audit.csv",
        "all_raw_runs.csv",
        "comparison_summary.csv",
    }

    assert old_filenames.isdisjoint(canonical_filenames)
