from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.common.file_hashing import sha256_file
from src.common.research_outputs import BATCH_SUMMARY_COLUMNS, RAW_RUN_COLUMNS
from src.experiments import run_paillier_phe_blockchain_experiment as runner
from src.experiments.run_paillier_phe_blockchain_experiment import (
    ENCRYPTED_EVIDENCE_INDEX_COLUMNS,
    PAILLIER_BLOCKCHAIN_AUDIT_COLUMNS,
    PAILLIER_PHE_BLOCKCHAIN_VARIANT,
    generate_paillier_keypair,
    run_paillier_phe_blockchain_experiment,
    run_timed_paillier_batch,
    write_encrypted_evidence_files,
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
        ]
    )


def fake_connection() -> SimpleNamespace:
    return SimpleNamespace(
        deployment={
            "address": "0x1234567890123456789012345678901234567890",
            "chainId": 31337,
            "rpcUrl": "http://127.0.0.1:8545",
        }
    )


def fake_record_paillier_batch_audit(**_kwargs):
    return {
        "record_status": "recorded",
        "correctness_pass": True,
        "blockchain_transaction_runtime_ms": 12.5,
        "gas_used": 345678,
        "transaction_hash": "0xabc",
        "block_number": 9,
        "effective_gas_price": 1_000_000_000,
        "blockchain_tx_count": 3,
        "audit_rows": [
            {
                "variant": PAILLIER_PHE_BLOCKCHAIN_VARIANT,
                "batch_id": _kwargs["batch_result"]["batch_id"],
                "stage": "openBatch",
                "status": "success",
                "transaction_hash": "0xopen",
                "block_number": 7,
                "gas_used": 100000,
                "effective_gas_price": 1_000_000_000,
                "fee_wei": 100000000000000,
                "nonce": 0,
                "transaction_index": 0,
                "receipt_status": 1,
                "submission_time_ms": 1.0,
                "mined_wait_time_ms": 2.0,
                "confirmation_wait_time_ms": 3.0,
                "total_chain_time_ms": 6.0,
                "confirmation_depth": _kwargs["confirmations"],
                "error_type": "",
                "error_message": "",
            },
            {
                "variant": PAILLIER_PHE_BLOCKCHAIN_VARIANT,
                "batch_id": _kwargs["batch_result"]["batch_id"],
                "stage": "closeBatch",
                "status": "success",
                "transaction_hash": "0xclose",
                "block_number": 8,
                "gas_used": 100000,
                "effective_gas_price": 1_000_000_000,
                "fee_wei": 100000000000000,
                "nonce": 1,
                "transaction_index": 0,
                "receipt_status": 1,
                "submission_time_ms": 1.0,
                "mined_wait_time_ms": 2.0,
                "confirmation_wait_time_ms": 3.0,
                "total_chain_time_ms": 6.0,
                "confirmation_depth": _kwargs["confirmations"],
                "error_type": "",
                "error_message": "",
            },
            {
                "variant": PAILLIER_PHE_BLOCKCHAIN_VARIANT,
                "batch_id": _kwargs["batch_result"]["batch_id"],
                "stage": "recordBatchAudit",
                "status": "success",
                "transaction_hash": "0xabc",
                "block_number": 9,
                "gas_used": 145678,
                "effective_gas_price": 1_000_000_000,
                "fee_wei": 145678000000000,
                "nonce": 2,
                "transaction_index": 0,
                "receipt_status": 1,
                "submission_time_ms": 1.0,
                "mined_wait_time_ms": 2.0,
                "confirmation_wait_time_ms": 3.0,
                "total_chain_time_ms": 6.5,
                "confirmation_depth": _kwargs["confirmations"],
                "error_type": "",
                "error_message": "",
            },
        ],
    }


def test_write_encrypted_evidence_files_omits_private_key_and_plaintext_orders(
    tmp_path: Path,
) -> None:
    public_key, private_key = generate_paillier_keypair(n_length=128)
    phe_output = run_timed_paillier_batch(sample_orders(), public_key, private_key)

    paths, hashes, index = write_encrypted_evidence_files(
        batch_orders=sample_orders(),
        phe_output=phe_output,
        public_key=public_key,
        key_size_bits=128,
        batch_evidence_dir=tmp_path,
    )

    assert set(paths) == {"encrypted_orders", "phe_result", "phe_metadata"}
    assert set(hashes) == {
        "encrypted_orders_hash",
        "phe_result_hash",
        "phe_metadata_hash",
    }
    assert list(index.columns) == ENCRYPTED_EVIDENCE_INDEX_COLUMNS
    encrypted_orders_text = paths["encrypted_orders"].read_text(encoding="utf-8")
    assert "order_00000001" not in encrypted_orders_text
    assert '"quantity":' not in encrypted_orders_text
    assert '"price":' not in encrypted_orders_text
    assert "private" not in encrypted_orders_text.lower()
    assert hashes["encrypted_orders_hash"] == sha256_file(paths["encrypted_orders"])


def test_run_paillier_phe_blockchain_experiment_writes_stage8_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results_root = tmp_path / "results"
    output_path = results_root / "paillier_phe_blockchain/csv/batch_summary.csv"
    raw_runs_path = results_root / "paillier_phe_blockchain/csv/raw_runs.csv"
    audit_path = results_root / "paillier_phe_blockchain/csv/blockchain_audit.csv"
    evidence_index_path = (
        results_root / "paillier_phe_blockchain/csv/encrypted_evidence_index.csv"
    )
    batch_evidence_dir = results_root / "paillier_phe_blockchain/batch_evidence"

    monkeypatch.setattr(runner, "connect_to_batch_audit", lambda *args, **kwargs: fake_connection())
    monkeypatch.setattr(
        runner,
        "record_paillier_batch_audit",
        fake_record_paillier_batch_audit,
    )

    results = run_paillier_phe_blockchain_experiment(
        input_path=tmp_path / "data/synthetic_orders.csv",
        output_path=output_path,
        raw_runs_output_path=raw_runs_path,
        blockchain_audit_output_path=audit_path,
        evidence_index_output_path=evidence_index_path,
        batch_evidence_dir=batch_evidence_dir,
        batch_sizes=(4,),
        warmup_runs=1,
        measured_runs=2,
        paillier_key_size=128,
        seed=7,
        confirmations=2,
    )

    assert output_path.exists()
    assert raw_runs_path.exists()
    assert audit_path.exists()
    assert evidence_index_path.exists()
    assert (batch_evidence_dir / "encrypted_orders_batch_0001.jsonl").exists()
    assert (batch_evidence_dir / "phe_result_batch_0001.json").exists()
    assert (batch_evidence_dir / "phe_metadata_batch_0001.json").exists()

    raw_runs = pd.read_csv(raw_runs_path)
    saved_results = pd.read_csv(output_path)
    audit = pd.read_csv(audit_path)
    evidence_index = pd.read_csv(evidence_index_path)

    assert results.iloc[0]["variant"] == PAILLIER_PHE_BLOCKCHAIN_VARIANT
    assert saved_results.iloc[0]["variant"] == PAILLIER_PHE_BLOCKCHAIN_VARIANT
    assert set(RAW_RUN_COLUMNS).issubset(raw_runs.columns)
    assert set(BATCH_SUMMARY_COLUMNS).issubset(saved_results.columns)
    assert {"buy_volume", "sell_volume", "total_runtime_ms", "transaction_hash"}.issubset(
        saved_results.columns
    )
    assert set(PAILLIER_BLOCKCHAIN_AUDIT_COLUMNS).issubset(audit.columns)
    assert list(evidence_index.columns) == ENCRYPTED_EVIDENCE_INDEX_COLUMNS
    assert set(audit["stage"]) == {"openBatch", "closeBatch", "recordBatchAudit"}
    assert saved_results["correctness_pass"].astype(str).str.lower().eq("true").all()
    assert saved_results.iloc[0]["blockchain_gas_used_total_mean"] == 345678
    assert saved_results.iloc[0]["ciphertext_size_bytes"] > 0
    assert len(evidence_index) == 3
    for _, row in evidence_index.iterrows():
        assert row["sha256_hash"] == sha256_file(row["file_path"])


def test_stage8_rejects_invalid_submission_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "connect_to_batch_audit", lambda *args, **kwargs: fake_connection())

    with pytest.raises(ValueError, match="submission_mode"):
        run_paillier_phe_blockchain_experiment(
            input_path=tmp_path / "data/synthetic_orders.csv",
            output_path=tmp_path / "results/paillier_phe_blockchain/csv/batch_summary.csv",
            batch_sizes=(2,),
            warmup_runs=0,
            measured_runs=1,
            paillier_key_size=128,
            submission_mode="invalid",
        )
