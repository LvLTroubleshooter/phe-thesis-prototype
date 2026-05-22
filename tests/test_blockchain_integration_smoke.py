import os
from pathlib import Path

import pandas as pd
import pytest

from src.experiments.generate_final_comparison import generate_final_comparison
from src.variants.blockchain.plaintext_blockchain_runner import (
    DEFAULT_DEPLOYMENT_PATH,
    PLAINTEXT_BLOCKCHAIN_VARIANT,
    connect_to_batch_audit,
    run_plaintext_blockchain_audit,
)


pytestmark = pytest.mark.integration


def integration_enabled() -> bool:
    return os.getenv("PHE_RUN_BLOCKCHAIN_INTEGRATION") == "1"


@pytest.mark.skipif(
    not integration_enabled(),
    reason="Set PHE_RUN_BLOCKCHAIN_INTEGRATION=1 with Hardhat running to enable.",
)
def test_real_plaintext_blockchain_smoke_writes_audited_outputs(tmp_path: Path) -> None:
    try:
        connection = connect_to_batch_audit(DEFAULT_DEPLOYMENT_PATH)
    except Exception as exc:  # pragma: no cover - only used in optional local smoke runs
        pytest.skip(f"Local BatchAudit deployment is not available: {exc}")

    if connection.contract.functions.batchExists(
        PLAINTEXT_BLOCKCHAIN_VARIANT,
        "batch_0001",
    ).call():
        pytest.skip(
            "batch_0001 already exists on-chain; restart Hardhat and redeploy for this smoke test."
        )

    results_root = tmp_path / "results"
    output_path = results_root / "plaintext_blockchain/csv/batch_summary.csv"
    raw_runs_path = results_root / "plaintext_blockchain/csv/raw_runs.csv"
    audit_path = results_root / "plaintext_blockchain/csv/blockchain_audit.csv"

    run_plaintext_blockchain_audit(
        input_path=tmp_path / "data/synthetic_orders.csv",
        output_path=output_path,
        raw_runs_output_path=raw_runs_path,
        blockchain_audit_output_path=audit_path,
        trades_output_path=results_root / "plaintext_blockchain/csv/trades.csv",
        unmatched_orders_output_path=results_root
        / "plaintext_blockchain/csv/unmatched_orders.csv",
        batch_sizes=(10, 20),
        warmup_runs=1,
        measured_runs=2,
    )
    generate_final_comparison(results_root)

    summary = pd.read_csv(output_path)
    audit = pd.read_csv(audit_path)
    comparison = pd.read_csv(results_root / "final_comparison/csv/comparison_summary.csv")

    assert output_path.exists()
    assert raw_runs_path.exists()
    assert audit_path.exists()
    assert summary["correctness_pass"].astype(str).str.lower().eq("true").all()
    assert audit["transaction_hash"].astype(str).str.len().gt(0).all()
    assert audit["gas_used"].gt(0).all()
    assert audit["block_number"].gt(0).all()
    assert "plaintext_blockchain" in set(comparison["variant"])
