from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.common.file_hashing import sha256_file
from src.common.metrics import COMMON_RESULT_COLUMNS
from src.variants.blockchain import plaintext_blockchain_runner
from src.variants.blockchain.plaintext_blockchain_runner import (
    BLOCKCHAIN_AUDIT_COLUMNS,
    DEFAULT_BLOCKCHAIN_RESULTS_PATH,
    DEFAULT_BLOCKCHAIN_TRADES_PATH,
    DEFAULT_BLOCKCHAIN_UNMATCHED_ORDERS_PATH,
    PLAINTEXT_BLOCKCHAIN_VARIANT,
    build_result_row_hash,
    blockchain_record_matches,
    compute_evidence_hashes,
    run_plaintext_blockchain_audit,
)


class FakeBatchRecord:
    def __init__(
        self,
        row: pd.Series,
        hashes: dict[str, str],
        result_row_hash: str,
    ) -> None:
        self.variant = PLAINTEXT_BLOCKCHAIN_VARIANT
        self.batchId = row["batch_id"]
        self.batchSize = int(row["batch_size"])
        self.buyVolume = int(row["buy_volume"])
        self.sellVolume = int(row["sell_volume"])
        self.matchedVolume = int(row["matched_volume"])
        self.executedTradeCount = int(row["executed_trade_count"])
        self.ordersFileHash = bytes.fromhex(hashes["orders_file_hash"])
        self.tradesFileHash = bytes.fromhex(hashes["trades_file_hash"])
        self.unmatchedOrdersFileHash = bytes.fromhex(
            hashes["unmatched_orders_file_hash"]
        )
        self.resultRowHash = bytes.fromhex(result_row_hash)


def sample_result_row() -> pd.Series:
    return pd.Series(
        {
            "variant": PLAINTEXT_BLOCKCHAIN_VARIANT,
            "batch_id": "batch_0001",
            "batch_size": 100,
            "buy_volume": 5000,
            "sell_volume": 4000,
            "matched_volume": 3500,
            "executed_trade_count": 20,
        }
    )


def test_compute_evidence_hashes_hashes_required_files(tmp_path: Path) -> None:
    orders = tmp_path / "orders.csv"
    trades = tmp_path / "trades.csv"
    unmatched = tmp_path / "unmatched.csv"
    orders.write_text("orders", encoding="utf-8")
    trades.write_text("trades", encoding="utf-8")
    unmatched.write_text("unmatched", encoding="utf-8")

    hashes = compute_evidence_hashes(orders, trades, unmatched)

    assert hashes["orders_file_hash"] == sha256_file(orders)
    assert hashes["trades_file_hash"] == sha256_file(trades)
    assert hashes["unmatched_orders_file_hash"] == sha256_file(unmatched)


def test_default_paths_use_organised_result_folders() -> None:
    assert (
        DEFAULT_BLOCKCHAIN_TRADES_PATH.as_posix()
        == "results/plaintext_blockchain/csv/trades.csv"
    )
    assert (
        DEFAULT_BLOCKCHAIN_UNMATCHED_ORDERS_PATH.as_posix()
        == "results/plaintext_blockchain/csv/unmatched_orders.csv"
    )
    assert (
        DEFAULT_BLOCKCHAIN_RESULTS_PATH.as_posix()
        == "results/plaintext_blockchain/csv/batch_summary.csv"
    )


def test_compute_evidence_hashes_reports_missing_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Missing plaintext \\+ blockchain evidence files"):
        compute_evidence_hashes(
            tmp_path / "orders.csv",
            tmp_path / "trades.csv",
            tmp_path / "unmatched.csv",
        )


def test_build_result_row_hash_is_stable() -> None:
    row = sample_result_row()

    assert build_result_row_hash(row) == build_result_row_hash(row.copy())


def test_blockchain_record_matches_expected_values() -> None:
    row = sample_result_row()
    hashes = {
        "orders_file_hash": "a" * 64,
        "trades_file_hash": "b" * 64,
        "unmatched_orders_file_hash": "c" * 64,
    }
    result_row_hash = "d" * 64
    record = FakeBatchRecord(row, hashes, result_row_hash)

    assert blockchain_record_matches(record, row, hashes, result_row_hash)


def test_run_plaintext_blockchain_audit_writes_common_schema(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orders_path = tmp_path / "synthetic_orders.csv"
    trades_path = tmp_path / "results/plaintext_blockchain/csv/plaintext_blockchain_trades.csv"
    unmatched_path = tmp_path / "results/plaintext_blockchain/csv/plaintext_blockchain_unmatched_orders.csv"
    output_path = tmp_path / "results/plaintext_blockchain/csv/results.csv"

    monkeypatch.setattr(
        plaintext_blockchain_runner,
        "connect_to_batch_audit",
        lambda *args, **kwargs: SimpleNamespace(
            deployment={
                "address": "0x1234567890123456789012345678901234567890",
                "chainId": 31337,
                "rpcUrl": "http://127.0.0.1:8545",
                "blockCreationTimeSeconds": 12,
                "blockGasLimit": 60_000_000,
                "initialBaseFeePerGas": 1_000_000_000,
            }
        ),
    )
    monkeypatch.setattr(
        plaintext_blockchain_runner,
        "record_plaintext_batch_audit",
        lambda **kwargs: {
            "record_status": "recorded",
            "correctness_pass": True,
            "blockchain_transaction_runtime_ms": 4.5,
            "gas_used": 123456,
            "transaction_hash": "0xabc",
            "block_number": 7,
            "effective_gas_price": 1000000000,
            "submitter": "0xdeployer",
            "tx_submission_time_s": 0.1,
            "tx_submission_to_mined_s": 0.2,
            "tx_mined_to_confirmed_s": 0.3,
            "tx_total_confirmation_s": 0.5,
            "pending_block_distance": 1,
            "included_block_number": 7,
            "confirmed_at_block_number": 9,
            "included_block_timestamp": 111,
            "confirmed_block_timestamp": 133,
            "base_fee_per_gas": 1000000000,
            "max_fee_per_gas": 1000000000,
            "max_priority_fee_per_gas": 0,
            "block_gas_limit": 60_000_000,
            "block_gas_used": 123456,
            "block_gas_used_percent": 0.2,
            "transaction_index": 0,
            "nonce": 0,
            "target_confirmations": 2,
            "submission_mode": "sequential",
            "revert_reason_if_failed": "",
        },
    )

    results, _, _ = run_plaintext_blockchain_audit(
        input_path=orders_path,
        trades_output_path=trades_path,
        unmatched_orders_output_path=unmatched_path,
        output_path=output_path,
        batch_sizes=(10,),
        warmup_runs=0,
        measured_runs=1,
    )

    saved_results = pd.read_csv(output_path)
    assert "matching_runtime_s_mean" in saved_results.columns
    assert "total_runtime_s_mean" in saved_results.columns
    assert "blockchain_runtime_s_mean" in saved_results.columns
    raw_runs_path = output_path.parent / "raw_runs.csv"
    audit_path = output_path.parent / "blockchain_audit.csv"
    assert raw_runs_path.exists()
    assert audit_path.exists()
    assert "matching_runtime_s_mean" in saved_results.columns
    assert "blockchain_runtime_s_mean" in saved_results.columns
    assert "audit_overhead_s_mean" in saved_results.columns
    assert "input_hash" in saved_results.columns
    assert output_path.parent.exists()
    assert trades_path.exists()
    assert unmatched_path.exists()
    assert results.iloc[0]["variant"] == "plaintext_blockchain"
    assert saved_results.iloc[0]["blockchain_runtime_s_mean"] == 0.0045
    assert saved_results.iloc[0]["total_runtime_s_mean"] > saved_results.iloc[0]["blockchain_runtime_s_mean"]
    assert saved_results.iloc[0]["audit_overhead_s_mean"] >= saved_results.iloc[0]["blockchain_runtime_s_mean"]
    assert saved_results.iloc[0]["unmatched_orders_count"] >= 0
    assert len(saved_results.iloc[0]["input_hash"]) == 64
    assert saved_results.iloc[0]["blockchain_gas_used_total_mean"] == 123456
    assert str(saved_results.iloc[0]["correctness_pass"]).lower() == "true"
    audit = pd.read_csv(audit_path)
    assert set(BLOCKCHAIN_AUDIT_COLUMNS).issubset(audit.columns)
    assert audit.iloc[0]["tx_submission_to_mined_s"] == 0.2
    assert audit.iloc[0]["tx_mined_to_confirmed_s"] == 0.3
    assert audit.iloc[0]["confirmed_at_block_number"] == 9
    assert audit.iloc[0]["submission_mode"] == "sequential"


def test_plaintext_blockchain_does_not_need_baseline_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plaintext_blockchain_runner,
        "connect_to_batch_audit",
        lambda *args, **kwargs: SimpleNamespace(
            deployment={
                "address": "0x1234567890123456789012345678901234567890",
                "chainId": 31337,
                "rpcUrl": "http://127.0.0.1:8545",
                "blockCreationTimeSeconds": 12,
                "blockGasLimit": 60_000_000,
                "initialBaseFeePerGas": 1_000_000_000,
            }
        ),
    )
    monkeypatch.setattr(
        plaintext_blockchain_runner,
        "record_plaintext_batch_audit",
        lambda **kwargs: {
            "record_status": "recorded",
            "correctness_pass": True,
            "blockchain_transaction_runtime_ms": 1.0,
            "gas_used": 1,
            "transaction_hash": "0xabc",
            "block_number": 1,
            "effective_gas_price": 0,
            "submitter": "0xdeployer",
            "submission_mode": "sequential",
        },
    )

    results, _, _ = run_plaintext_blockchain_audit(
        input_path=tmp_path / "data/synthetic_orders.csv",
        output_path=tmp_path / "results/plaintext_blockchain/csv/results.csv",
        trades_output_path=tmp_path / "results/plaintext_blockchain/csv/trades.csv",
        unmatched_orders_output_path=tmp_path / "results/plaintext_blockchain/csv/unmatched.csv",
        batch_sizes=(5,),
        warmup_runs=0,
        measured_runs=1,
    )

    assert len(results) == 1
    assert not (tmp_path / "results/plaintext_baseline/csv/plaintext_baseline_results.csv").exists()


def test_missing_blockchain_node_gives_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plaintext_blockchain_runner,
        "load_deployment",
        lambda *_args, **_kwargs: {
            "address": "0x1234567890123456789012345678901234567890",
            "chainId": 31337,
            "rpcUrl": "http://127.0.0.1:1",
            "abi": [],
        },
    )

    with pytest.raises(ConnectionError, match="Start it with"):
        plaintext_blockchain_runner.connect_to_batch_audit(tmp_path / "deployment.json")


def test_plaintext_blockchain_rejects_invalid_submission_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plaintext_blockchain_runner,
        "connect_to_batch_audit",
        lambda *args, **kwargs: SimpleNamespace(
            deployment={
                "address": "0x1234567890123456789012345678901234567890",
                "chainId": 31337,
                "rpcUrl": "http://127.0.0.1:8545",
                "blockCreationTimeSeconds": 12,
                "blockGasLimit": 60_000_000,
                "initialBaseFeePerGas": 1_000_000_000,
            }
        ),
    )

    with pytest.raises(ValueError, match="submission_mode"):
        run_plaintext_blockchain_audit(
            input_path=tmp_path / "data/synthetic_orders.csv",
            output_path=tmp_path / "results/plaintext_blockchain/csv/results.csv",
            batch_sizes=(5,),
            warmup_runs=0,
            measured_runs=1,
            submission_mode="invalid",
        )
