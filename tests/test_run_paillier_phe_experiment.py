from pathlib import Path

import pandas as pd

from src.common.research_outputs import BATCH_SUMMARY_COLUMNS, RAW_RUN_COLUMNS
from src.experiments.run_paillier_phe_experiment import (
    DEFAULT_EXPERIMENT_BATCH_SIZES,
    main,
    run_paillier_phe_experiment,
)


def test_run_paillier_phe_experiment_writes_canonical_outputs(tmp_path: Path) -> None:
    results_root = tmp_path / "results"
    input_path = tmp_path / "data/synthetic_orders.csv"
    output_path = results_root / "paillier_phe/csv/batch_summary.csv"
    raw_runs_path = results_root / "paillier_phe/csv/raw_runs.csv"
    batch_evidence_dir = results_root / "paillier_phe/batch_evidence"

    results = run_paillier_phe_experiment(
        input_path=input_path,
        output_path=output_path,
        raw_runs_output_path=raw_runs_path,
        batch_evidence_dir=batch_evidence_dir,
        batch_sizes=(4, 6),
        warmup_runs=1,
        measured_runs=2,
        key_size_bits=128,
        seed=7,
    )

    assert input_path.exists()
    assert output_path.exists()
    assert raw_runs_path.exists()
    assert (batch_evidence_dir / "batch_0001_orders.csv").exists()
    assert (batch_evidence_dir / "batch_0001_paillier_aggregate.csv").exists()
    assert (batch_evidence_dir / "batch_0002_orders.csv").exists()
    assert (batch_evidence_dir / "batch_0002_paillier_aggregate.csv").exists()
    raw_runs = pd.read_csv(raw_runs_path)
    saved_results = pd.read_csv(output_path)
    evidence = pd.read_csv(batch_evidence_dir / "batch_0001_paillier_aggregate.csv")

    assert results["variant"].unique().tolist() == ["paillier_phe"]
    assert saved_results["variant"].unique().tolist() == ["paillier_phe"]
    assert set(RAW_RUN_COLUMNS).issubset(raw_runs.columns)
    assert set(BATCH_SUMMARY_COLUMNS).issubset(saved_results.columns)
    assert raw_runs["is_warmup"].astype(str).str.lower().tolist().count("true") == 2
    assert raw_runs["is_warmup"].astype(str).str.lower().tolist().count("false") == 4
    assert saved_results["correctness_pass"].astype(str).str.lower().eq("true").all()
    assert saved_results["ciphertext_size_bytes"].gt(0).all()
    assert saved_results["encryption_runtime_s_mean"].gt(0).all()
    assert saved_results["encrypted_computation_runtime_s_mean"].gt(0).all()
    assert saved_results["decryption_runtime_s_mean"].gt(0).all()
    assert saved_results["blockchain_runtime_s_mean"].eq(0).all()
    assert saved_results["blockchain_tx_count_mean"].eq(0).all()
    assert evidence.iloc[0]["variant"] == "paillier_phe"
    assert bool(evidence.iloc[0]["correctness_pass"]) is True
    assert int(evidence.iloc[0]["ciphertext_size_bytes"]) > 0


def test_paillier_main_writes_figures_and_refreshes_comparison(tmp_path: Path, capsys) -> None:
    results_root = tmp_path / "results"
    output_path = results_root / "paillier_phe/csv/batch_summary.csv"
    raw_runs_path = results_root / "paillier_phe/csv/raw_runs.csv"
    figures_dir = results_root / "paillier_phe/figures"
    batch_evidence_dir = results_root / "paillier_phe/batch_evidence"

    main(
        [
            "--input",
            str(tmp_path / "data/synthetic_orders.csv"),
            "--output",
            str(output_path),
            "--raw-runs-output",
            str(raw_runs_path),
            "--batch-evidence-dir",
            str(batch_evidence_dir),
            "--figures-dir",
            str(figures_dir),
            "--batch-sizes",
            "3",
            "--warmup-runs",
            "1",
            "--measured-runs",
            "2",
            "--key-size-bits",
            "128",
            "--skip-cache-cleanup",
        ]
    )

    assert output_path.exists()
    assert raw_runs_path.exists()
    assert (batch_evidence_dir / "batch_0001_orders.csv").exists()
    assert (batch_evidence_dir / "batch_0001_paillier_aggregate.csv").exists()
    assert (figures_dir / "paillier_phe_runtime.png").exists()
    assert (figures_dir / "paillier_phe_throughput.png").exists()
    assert (figures_dir / "paillier_phe_components.png").exists()
    assert (figures_dir / "paillier_phe_ciphertext_size.png").exists()
    assert (results_root / "final_comparison/csv/comparison_summary.csv").exists()
    output = capsys.readouterr().out
    assert "Processing batch_0001 | batch size: 3" in output
    assert "Completed batch_0001 | batch size: 3 | runtime:" in output


def test_default_paillier_batch_sizes_are_small_enough_for_real_phe() -> None:
    assert DEFAULT_EXPERIMENT_BATCH_SIZES == (100, 500, 1_000)
