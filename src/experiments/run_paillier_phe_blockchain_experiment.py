"""Run Paillier/PHE encrypted aggregation with blockchain audit evidence."""

from __future__ import annotations

import argparse
import contextlib
import gc
import io
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Sequence

import pandas as pd

from src.common.cleanup import clean_python_caches
from src.common.file_hashing import hex_digest_to_bytes32, sha256_file, sha256_mapping, sha256_text
from src.common.metrics import (
    apply_common_result_schema,
    calculate_throughput,
    file_size_bytes,
    save_dataframe,
)
from src.common.order_schema import validate_orders
from src.common.research_outputs import (
    RAW_RUN_COLUMNS,
    apply_wall_clock_runtime_columns,
    manifest_by_batch,
    summarize_measured_runs,
    utc_now_iso,
    write_command_wall_clock_runtime,
    write_dataset_manifest,
)
from src.common.synthetic_orders import DEFAULT_SYNTHETIC_ORDERS_PATH
from src.experiments.run_plaintext_baseline import infer_results_root, load_or_generate_orders
from src.variants.blockchain.plaintext_blockchain_runner import (
    DEFAULT_CONFIRMATIONS,
    DEFAULT_DEPLOYMENT_PATH,
    DEFAULT_SUBMISSION_MODE,
    SUBMISSION_MODES,
    BlockchainConnection,
    bytes32_to_hex,
    connect_to_batch_audit,
    record_field,
    transact_and_measure,
)
from src.variants.paillier_phe.aggregation import (
    aggregate_encrypted_columns,
    decrypt_aggregate_totals,
    encrypt_order_quantities,
    generate_paillier_keypair,
    plaintext_aggregate_reference,
)
from src.visualization.visualize_paillier_phe_blockchain_results import (
    DEFAULT_OUTPUT_DIR as DEFAULT_FIGURES_DIR,
)
from src.visualization.visualize_paillier_phe_blockchain_results import (
    create_paillier_phe_blockchain_visualizations,
)

PAILLIER_PHE_BLOCKCHAIN_VARIANT = "paillier_phe_blockchain"
DEFAULT_RESULTS_PATH = Path("results/paillier_phe_blockchain/csv/batch_summary.csv")
DEFAULT_RAW_RUNS_PATH = Path("results/paillier_phe_blockchain/csv/raw_runs.csv")
DEFAULT_AUDIT_PATH = Path("results/paillier_phe_blockchain/csv/blockchain_audit.csv")
DEFAULT_EVIDENCE_INDEX_PATH = Path(
    "results/paillier_phe_blockchain/csv/encrypted_evidence_index.csv"
)
DEFAULT_BATCH_EVIDENCE_DIR = Path("results/paillier_phe_blockchain/batch_evidence")
DEFAULT_EXPERIMENT_BATCH_SIZES = (100, 500, 1_000)
DEFAULT_WARMUP_RUNS = 1
DEFAULT_MEASURED_RUNS = 5
DEFAULT_KEY_SIZE_BITS = 2048
EXECUTED_TRADE_COUNT = 0

PAILLIER_BLOCKCHAIN_AUDIT_COLUMNS = [
    "variant",
    "batch_id",
    "stage",
    "status",
    "transaction_hash",
    "block_number",
    "gas_used",
    "effective_gas_price",
    "fee_wei",
    "nonce",
    "transaction_index",
    "receipt_status",
    "submission_time_ms",
    "mined_wait_time_ms",
    "confirmation_wait_time_ms",
    "total_chain_time_ms",
    "confirmation_depth",
    "error_type",
    "error_message",
]

ENCRYPTED_EVIDENCE_INDEX_COLUMNS = [
    "variant",
    "batch_id",
    "evidence_type",
    "file_path",
    "sha256_hash",
    "file_size_bytes",
    "public_key_n_hash",
    "created_at",
]


def public_key_n_hash(public_key: Any) -> str:
    """Hash the Paillier public modulus without exposing private key material."""
    return sha256_text(str(int(public_key.n)))


def encrypted_number_to_hex(encrypted_number: Any) -> str:
    """Serialize a Paillier encrypted number as a base-16 ciphertext integer."""
    return format(int(encrypted_number.ciphertext(be_secure=False)), "x")


def order_id_hash(order_id: Any) -> str:
    """Hash an order identifier before storing encrypted evidence."""
    return sha256_text(str(order_id))


def run_timed_paillier_batch(
    batch_orders: pd.DataFrame,
    public_key: Any,
    private_key: Any,
) -> dict[str, Any]:
    """Run Stage 7 PHE aggregation while keeping ciphertexts for evidence."""
    reference = plaintext_aggregate_reference(batch_orders)

    started_at = perf_counter()
    encrypted_columns = encrypt_order_quantities(batch_orders, public_key)
    encryption_runtime_s = perf_counter() - started_at

    started_at = perf_counter()
    encrypted_total_buy, encrypted_total_sell = aggregate_encrypted_columns(
        encrypted_columns,
        public_key,
    )
    encrypted_computation_runtime_s = perf_counter() - started_at

    started_at = perf_counter()
    buy_volume, sell_volume = decrypt_aggregate_totals(
        encrypted_total_buy,
        encrypted_total_sell,
        private_key,
    )
    decryption_runtime_s = perf_counter() - started_at

    matched_volume = min(buy_volume, sell_volume)
    result = {
        "batch_id": str(reference["batch_id"]),
        "n_orders": int(reference["n_orders"]),
        "buy_order_count": int(reference["buy_order_count"]),
        "sell_order_count": int(reference["sell_order_count"]),
        "buy_volume": buy_volume,
        "sell_volume": sell_volume,
        "matched_volume": matched_volume,
        "reference_buy_volume": int(reference["buy_volume"]),
        "reference_sell_volume": int(reference["sell_volume"]),
        "reference_matched_volume": int(reference["matched_volume"]),
        "correctness_pass": (
            buy_volume == int(reference["buy_volume"])
            and sell_volume == int(reference["sell_volume"])
            and matched_volume == int(reference["matched_volume"])
        ),
    }
    return {
        "result": result,
        "encrypted_columns": encrypted_columns,
        "encrypted_total_buy": encrypted_total_buy,
        "encrypted_total_sell": encrypted_total_sell,
        "encryption_runtime_s": encryption_runtime_s,
        "encrypted_computation_runtime_s": encrypted_computation_runtime_s,
        "decryption_runtime_s": decryption_runtime_s,
        "ciphertext_size_bytes": int(encrypted_columns.ciphertext_size_bytes),
    }


def build_paillier_blockchain_result_hash(
    *,
    batch_result: dict[str, Any],
    public_key_hash: str,
    evidence_hashes: dict[str, str],
) -> str:
    """Hash the stable off-chain PHE result audited by BatchAudit.resultRowHash."""
    return sha256_mapping(
        {
            "variant": PAILLIER_PHE_BLOCKCHAIN_VARIANT,
            "batch_id": batch_result["batch_id"],
            "batch_size": int(batch_result["n_orders"]),
            "buy_volume": int(batch_result["buy_volume"]),
            "sell_volume": int(batch_result["sell_volume"]),
            "matched_volume": int(batch_result["matched_volume"]),
            "executed_trade_count": EXECUTED_TRADE_COUNT,
            "correctness_pass": bool(batch_result["correctness_pass"]),
            "public_key_n_hash": public_key_hash,
            "encrypted_orders_hash": evidence_hashes["encrypted_orders_hash"],
            "phe_result_hash": evidence_hashes["phe_result_hash"],
            "phe_metadata_hash": evidence_hashes["phe_metadata_hash"],
        }
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a stable JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def write_encrypted_evidence_files(
    *,
    batch_orders: pd.DataFrame,
    phe_output: dict[str, Any],
    public_key: Any,
    key_size_bits: int,
    batch_evidence_dir: Path,
) -> tuple[dict[str, Path], dict[str, str], pd.DataFrame]:
    """Write encrypted order evidence, aggregate result, metadata, and index rows."""
    result = phe_output["result"]
    batch_id = str(result["batch_id"])
    key_hash = public_key_n_hash(public_key)
    encrypted_orders_path = batch_evidence_dir / f"encrypted_orders_{batch_id}.jsonl"
    phe_result_path = batch_evidence_dir / f"phe_result_{batch_id}.json"
    metadata_path = batch_evidence_dir / f"phe_metadata_{batch_id}.json"

    batch_evidence_dir.mkdir(parents=True, exist_ok=True)
    encrypted_columns = phe_output["encrypted_columns"]
    validated = validate_orders(batch_orders)
    with encrypted_orders_path.open("w", encoding="utf-8") as file:
        for order, encrypted_buy, encrypted_sell in zip(
            validated.itertuples(index=False),
            encrypted_columns.encrypted_buy_quantities,
            encrypted_columns.encrypted_sell_quantities,
            strict=True,
        ):
            file.write(
                json.dumps(
                    {
                        "batch_id": batch_id,
                        "order_id_hash": order_id_hash(order.order_id),
                        "encrypted_buy_quantity": encrypted_number_to_hex(encrypted_buy),
                        "encrypted_sell_quantity": encrypted_number_to_hex(encrypted_sell),
                        "ciphertext_base": 16,
                        "public_key_n_hash": key_hash,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    write_json(
        phe_result_path,
        {
            "variant": PAILLIER_PHE_BLOCKCHAIN_VARIANT,
            "batch_id": batch_id,
            "batch_size": int(result["n_orders"]),
            "buy_volume": int(result["buy_volume"]),
            "sell_volume": int(result["sell_volume"]),
            "matched_volume": int(result["matched_volume"]),
            "reference_buy_volume": int(result["reference_buy_volume"]),
            "reference_sell_volume": int(result["reference_sell_volume"]),
            "reference_matched_volume": int(result["reference_matched_volume"]),
            "correctness_pass": bool(result["correctness_pass"]),
            "ciphertext_size_bytes": int(phe_output["ciphertext_size_bytes"]),
            "encrypted_total_buy": encrypted_number_to_hex(phe_output["encrypted_total_buy"]),
            "encrypted_total_sell": encrypted_number_to_hex(phe_output["encrypted_total_sell"]),
            "ciphertext_base": 16,
            "public_key_n_hash": key_hash,
            "created_at": utc_now_iso(),
        },
    )
    write_json(
        metadata_path,
        {
            "variant": PAILLIER_PHE_BLOCKCHAIN_VARIANT,
            "batch_id": batch_id,
            "batch_size": int(result["n_orders"]),
            "key_size_bits": int(key_size_bits),
            "public_key_n_hash": key_hash,
            "ciphertext_base": 16,
            "encrypted_order_count": int(result["n_orders"]),
            "evidence_format": "jsonl_encrypted_orders_plus_json_aggregate",
            "private_key_material_stored": False,
            "individual_plaintext_quantities_stored": False,
            "individual_plaintext_prices_stored": False,
            "created_at": utc_now_iso(),
        },
    )

    evidence_paths = {
        "encrypted_orders": encrypted_orders_path,
        "phe_result": phe_result_path,
        "phe_metadata": metadata_path,
    }
    evidence_hashes = {
        "encrypted_orders_hash": sha256_file(encrypted_orders_path),
        "phe_result_hash": sha256_file(phe_result_path),
        "phe_metadata_hash": sha256_file(metadata_path),
    }
    index_rows = pd.DataFrame(
        [
            {
                "variant": PAILLIER_PHE_BLOCKCHAIN_VARIANT,
                "batch_id": batch_id,
                "evidence_type": evidence_type,
                "file_path": str(path),
                "sha256_hash": evidence_hashes[f"{evidence_type}_hash"],
                "file_size_bytes": file_size_bytes(path),
                "public_key_n_hash": key_hash,
                "created_at": utc_now_iso(),
            }
            for evidence_type, path in evidence_paths.items()
        ],
        columns=ENCRYPTED_EVIDENCE_INDEX_COLUMNS,
    )
    return evidence_paths, evidence_hashes, index_rows


def paillier_blockchain_record_matches(
    record: Any,
    *,
    batch_result: dict[str, Any],
    evidence_hashes: dict[str, str],
    result_hash: str,
) -> bool:
    """Verify BatchAudit stores the expected PHE evidence hashes and aggregates."""
    return (
        record_field(record, "variant") == PAILLIER_PHE_BLOCKCHAIN_VARIANT
        and record_field(record, "batchId") == str(batch_result["batch_id"])
        and int(record_field(record, "batchSize")) == int(batch_result["n_orders"])
        and int(record_field(record, "buyVolume")) == int(batch_result["buy_volume"])
        and int(record_field(record, "sellVolume")) == int(batch_result["sell_volume"])
        and int(record_field(record, "matchedVolume")) == int(batch_result["matched_volume"])
        and int(record_field(record, "executedTradeCount")) == EXECUTED_TRADE_COUNT
        and bytes32_to_hex(record_field(record, "ordersFileHash"))
        == evidence_hashes["encrypted_orders_hash"]
        and bytes32_to_hex(record_field(record, "tradesFileHash"))
        == evidence_hashes["phe_result_hash"]
        and bytes32_to_hex(record_field(record, "unmatchedOrdersFileHash"))
        == evidence_hashes["phe_metadata_hash"]
        and bytes32_to_hex(record_field(record, "resultRowHash")) == result_hash
    )


def audit_row_from_tx(
    *,
    batch_id: str,
    stage: str,
    status: str,
    tx_result: dict[str, Any],
    confirmations: int,
    error_message: str = "",
) -> dict[str, Any]:
    """Build one requested blockchain_audit.csv lifecycle row."""
    gas_used = int(tx_result.get("gas_used", 0))
    effective_gas_price = int(tx_result.get("effective_gas_price", 0))
    return {
        "variant": PAILLIER_PHE_BLOCKCHAIN_VARIANT,
        "batch_id": batch_id,
        "stage": stage,
        "status": status,
        "transaction_hash": tx_result.get("transaction_hash", ""),
        "block_number": int(tx_result.get("block_number", 0)),
        "gas_used": gas_used,
        "effective_gas_price": effective_gas_price,
        "fee_wei": gas_used * effective_gas_price,
        "nonce": int(tx_result.get("nonce", 0)),
        "transaction_index": int(tx_result.get("transaction_index", 0)),
        "receipt_status": int(tx_result.get("status_code", 0)),
        "submission_time_ms": float(tx_result.get("tx_submission_time_s", 0.0)) * 1_000,
        "mined_wait_time_ms": float(tx_result.get("tx_submission_to_mined_s", 0.0)) * 1_000,
        "confirmation_wait_time_ms": float(tx_result.get("tx_mined_to_confirmed_s", 0.0)) * 1_000,
        "total_chain_time_ms": float(tx_result.get("tx_total_confirmation_s", 0.0)) * 1_000,
        "confirmation_depth": confirmations,
        "error_type": tx_result.get("error_type", ""),
        "error_message": error_message or tx_result.get("revert_reason_if_failed", ""),
    }


def empty_tx_result(status_code: int = 1) -> dict[str, Any]:
    """Return zero-valued transaction fields for already-existing records."""
    return {
        "status_code": status_code,
        "gas_used": 0,
        "effective_gas_price": 0,
        "transaction_hash": "",
        "block_number": 0,
        "nonce": 0,
        "transaction_index": 0,
        "tx_submission_time_s": 0.0,
        "tx_submission_to_mined_s": 0.0,
        "tx_mined_to_confirmed_s": 0.0,
        "tx_total_confirmation_s": 0.0,
        "error_type": "",
        "revert_reason_if_failed": "",
    }


def failed_paillier_blockchain_result(
    *,
    batch_id: str,
    error_type: str,
    error_message: str,
    failed_stage: str,
    confirmations: int,
) -> dict[str, Any]:
    """Build a failed audit result with one lifecycle row."""
    tx_result = empty_tx_result(status_code=0)
    tx_result["error_type"] = error_type
    return {
        "record_status": "failed",
        "correctness_pass": False,
        "blockchain_transaction_runtime_ms": 0.0,
        "gas_used": 0,
        "transaction_hash": "",
        "block_number": 0,
        "effective_gas_price": 0,
        "blockchain_tx_count": 0,
        "audit_rows": [
            audit_row_from_tx(
                batch_id=batch_id,
                stage=failed_stage,
                status="failed",
                tx_result=tx_result,
                confirmations=confirmations,
                error_message=error_message,
            )
        ],
    }


def record_paillier_batch_audit(
    *,
    connection: BlockchainConnection,
    batch_result: dict[str, Any],
    evidence_hashes: dict[str, str],
    result_hash: str,
    confirmations: int = DEFAULT_CONFIRMATIONS,
    submission_mode: str = DEFAULT_SUBMISSION_MODE,
) -> dict[str, Any]:
    """Write PHE evidence hashes to the reusable BatchAudit lifecycle."""
    if submission_mode not in SUBMISSION_MODES:
        raise ValueError(
            f"submission_mode must be one of: {', '.join(sorted(SUBMISSION_MODES))}"
        )
    contract = connection.contract
    batch_id = str(batch_result["batch_id"])

    if contract.functions.batchExists(PAILLIER_PHE_BLOCKCHAIN_VARIANT, batch_id).call():
        record = contract.functions.getBatchAudit(
            PAILLIER_PHE_BLOCKCHAIN_VARIANT,
            batch_id,
        ).call()
        correctness_pass = paillier_blockchain_record_matches(
            record,
            batch_result=batch_result,
            evidence_hashes=evidence_hashes,
            result_hash=result_hash,
        )
        status = "already_exists" if correctness_pass else "failed"
        return {
            "record_status": status,
            "correctness_pass": correctness_pass,
            "blockchain_transaction_runtime_ms": 0.0,
            "gas_used": 0,
            "transaction_hash": "",
            "block_number": int(record_field(record, "recordedBlock")),
            "effective_gas_price": 0,
            "blockchain_tx_count": 0,
            "audit_rows": [
                audit_row_from_tx(
                    batch_id=batch_id,
                    stage="recordBatchAudit",
                    status=status,
                    tx_result=empty_tx_result(status_code=1 if correctness_pass else 0),
                    confirmations=confirmations,
                    error_message="" if correctness_pass else "existing record does not match evidence",
                )
            ],
        }

    open_call = contract.functions.openBatch(
        PAILLIER_PHE_BLOCKCHAIN_VARIANT,
        batch_id,
        hex_digest_to_bytes32(evidence_hashes["encrypted_orders_hash"]),
    )
    close_call = contract.functions.closeBatch(
        PAILLIER_PHE_BLOCKCHAIN_VARIANT,
        batch_id,
        hex_digest_to_bytes32(result_hash),
    )
    audit_call = contract.functions.recordBatchAudit(
        PAILLIER_PHE_BLOCKCHAIN_VARIANT,
        batch_id,
        int(batch_result["n_orders"]),
        int(batch_result["buy_volume"]),
        int(batch_result["sell_volume"]),
        int(batch_result["matched_volume"]),
        EXECUTED_TRADE_COUNT,
        hex_digest_to_bytes32(evidence_hashes["encrypted_orders_hash"]),
        hex_digest_to_bytes32(evidence_hashes["phe_result_hash"]),
        hex_digest_to_bytes32(evidence_hashes["phe_metadata_hash"]),
        hex_digest_to_bytes32(result_hash),
    )

    lifecycle: list[tuple[str, dict[str, Any]]] = []
    try:
        lifecycle.append(("openBatch", transact_and_measure(connection, open_call, confirmations)))
        lifecycle.append(("closeBatch", transact_and_measure(connection, close_call, confirmations)))
        lifecycle.append(
            ("recordBatchAudit", transact_and_measure(connection, audit_call, confirmations))
        )
    except TimeoutError as error:
        return failed_paillier_blockchain_result(
            batch_id=batch_id,
            error_type="transaction_timeout",
            error_message=str(error),
            failed_stage="transaction_lifecycle",
            confirmations=confirmations,
        )
    except ValueError as error:
        return failed_paillier_blockchain_result(
            batch_id=batch_id,
            error_type="transaction_reverted",
            error_message=str(error),
            failed_stage="transaction_lifecycle",
            confirmations=confirmations,
        )
    except Exception as error:
        return failed_paillier_blockchain_result(
            batch_id=batch_id,
            error_type=type(error).__name__,
            error_message=str(error),
            failed_stage="transaction_lifecycle",
            confirmations=confirmations,
        )

    record = contract.functions.getBatchAudit(PAILLIER_PHE_BLOCKCHAIN_VARIANT, batch_id).call()
    correctness_pass = paillier_blockchain_record_matches(
        record,
        batch_result=batch_result,
        evidence_hashes=evidence_hashes,
        result_hash=result_hash,
    )
    audit_rows = [
        audit_row_from_tx(
            batch_id=batch_id,
            stage=stage,
            status="success" if int(tx_result.get("status_code", 0)) == 1 else "failed",
            tx_result=tx_result,
            confirmations=confirmations,
        )
        for stage, tx_result in lifecycle
    ]
    audit_tx = lifecycle[-1][1]
    total_runtime_ms = sum(
        float(tx_result.get("tx_total_confirmation_s", 0.0)) * 1_000
        for _, tx_result in lifecycle
    )
    total_gas_used = sum(int(tx_result.get("gas_used", 0)) for _, tx_result in lifecycle)
    return {
        "record_status": "recorded" if correctness_pass else "failed",
        "correctness_pass": correctness_pass,
        "blockchain_transaction_runtime_ms": total_runtime_ms,
        "gas_used": total_gas_used,
        "transaction_hash": audit_tx.get("transaction_hash", ""),
        "block_number": int(audit_tx.get("block_number", 0)),
        "effective_gas_price": int(audit_tx.get("effective_gas_price", 0)),
        "blockchain_tx_count": len(lifecycle),
        "audit_rows": audit_rows,
    }


def build_raw_run_row(
    *,
    phe_output: dict[str, Any],
    run_id: str,
    is_warmup: bool,
    seed: int,
    input_hash: str,
    evidence_write_runtime_s: float = 0.0,
    hashing_runtime_s: float = 0.0,
    blockchain_runtime_s: float = 0.0,
    tx_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one raw run row with canonical and common ablation columns."""
    result = phe_output["result"]
    n_orders = int(result["n_orders"])
    encryption_runtime_s = float(phe_output["encryption_runtime_s"])
    encrypted_computation_runtime_s = float(phe_output["encrypted_computation_runtime_s"])
    decryption_runtime_s = float(phe_output["decryption_runtime_s"])
    total_runtime_s = (
        encryption_runtime_s
        + encrypted_computation_runtime_s
        + decryption_runtime_s
        + evidence_write_runtime_s
        + hashing_runtime_s
        + blockchain_runtime_s
    )
    tx = tx_result or {}
    row = {
        "experiment_name": PAILLIER_PHE_BLOCKCHAIN_VARIANT,
        "variant": PAILLIER_PHE_BLOCKCHAIN_VARIANT,
        "batch_id": result["batch_id"],
        "batch_size": n_orders,
        "run_id": run_id,
        "is_warmup": is_warmup,
        "seed": seed,
        "input_hash": input_hash,
        "ciphertext_size_bytes": int(phe_output["ciphertext_size_bytes"]),
        "matching_runtime_s": 0.0,
        "encryption_runtime_s": encryption_runtime_s,
        "encrypted_computation_runtime_s": encrypted_computation_runtime_s,
        "decryption_runtime_s": decryption_runtime_s,
        "evidence_write_runtime_s": evidence_write_runtime_s,
        "hashing_runtime_s": hashing_runtime_s,
        "blockchain_runtime_s": blockchain_runtime_s,
        "total_runtime_s": total_runtime_s,
        "throughput_orders_per_second": calculate_throughput(n_orders, total_runtime_s),
        "matched_volume": int(result["matched_volume"]),
        "matched_trades_count": EXECUTED_TRADE_COUNT,
        "unmatched_orders_count": 0,
        "correctness_pass": bool(result["correctness_pass"])
        and bool(tx.get("correctness_pass", True)),
        "blockchain_tx_count": int(tx.get("blockchain_tx_count", 0)),
        "blockchain_gas_used_total": int(tx.get("gas_used", 0)),
        "blockchain_block_number": int(tx.get("block_number", 0)),
        "blockchain_transaction_hash": tx.get("transaction_hash", ""),
        "created_at": utc_now_iso(),
        "buy_volume": int(result["buy_volume"]),
        "sell_volume": int(result["sell_volume"]),
        "executed_trade_count": EXECUTED_TRADE_COUNT,
        "total_runtime_ms": total_runtime_s * 1_000,
        "encryption_time_ms": encryption_runtime_s * 1_000,
        "encrypted_computation_time_ms": encrypted_computation_runtime_s * 1_000,
        "decryption_time_ms": decryption_runtime_s * 1_000,
        "blockchain_time_ms": blockchain_runtime_s * 1_000,
        "gas_used": int(tx.get("gas_used", 0)),
        "block_number": int(tx.get("block_number", 0)),
        "transaction_hash": tx.get("transaction_hash", ""),
    }
    return row


def add_common_summary_columns(
    summary: pd.DataFrame,
    raw_runs: pd.DataFrame,
) -> pd.DataFrame:
    """Add common ablation columns while preserving canonical summary columns."""
    result = summary.copy()
    measured = raw_runs[raw_runs["is_warmup"] == False].copy()
    for index, row in result.iterrows():
        batch_id = str(row["batch_id"])
        group = measured[measured["batch_id"].astype(str) == batch_id]
        if group.empty:
            continue
        last = group.iloc[-1]
        result.at[index, "buy_volume"] = int(last["buy_volume"])
        result.at[index, "sell_volume"] = int(last["sell_volume"])
        result.at[index, "executed_trade_count"] = EXECUTED_TRADE_COUNT
        result.at[index, "total_runtime_s"] = float(row["total_runtime_s_mean"])
        result.at[index, "total_runtime_ms"] = float(row["total_runtime_s_mean"]) * 1_000
        result.at[index, "throughput_orders_per_second"] = float(
            row["throughput_orders_per_second_mean"]
        )
        result.at[index, "encryption_time_ms"] = float(row["encryption_runtime_s_mean"]) * 1_000
        result.at[index, "encrypted_computation_time_ms"] = (
            float(row["encrypted_computation_runtime_s_mean"]) * 1_000
        )
        result.at[index, "decryption_time_ms"] = float(row["decryption_runtime_s_mean"]) * 1_000
        result.at[index, "blockchain_time_ms"] = float(row["blockchain_runtime_s_mean"]) * 1_000
        result.at[index, "gas_used"] = int(group["blockchain_gas_used_total"].max())
        result.at[index, "block_number"] = int(group["blockchain_block_number"].max())
        result.at[index, "transaction_hash"] = str(group["blockchain_transaction_hash"].iloc[-1])
    return apply_common_result_schema(result)


def refresh_final_comparison(results_root: Path) -> None:
    """Regenerate final comparison outputs from current experiment results."""
    from src.experiments.generate_final_comparison import generate_final_comparison

    with contextlib.redirect_stdout(io.StringIO()):
        generate_final_comparison(results_root)


def run_paillier_phe_blockchain_experiment(
    input_path: Path = DEFAULT_SYNTHETIC_ORDERS_PATH,
    deployment_path: Path = DEFAULT_DEPLOYMENT_PATH,
    output_path: Path = DEFAULT_RESULTS_PATH,
    raw_runs_output_path: Path = DEFAULT_RAW_RUNS_PATH,
    blockchain_audit_output_path: Path = DEFAULT_AUDIT_PATH,
    evidence_index_output_path: Path = DEFAULT_EVIDENCE_INDEX_PATH,
    batch_evidence_dir: Path = DEFAULT_BATCH_EVIDENCE_DIR,
    batch_sizes: tuple[int, ...] | None = DEFAULT_EXPERIMENT_BATCH_SIZES,
    warmup_runs: int = DEFAULT_WARMUP_RUNS,
    measured_runs: int = DEFAULT_MEASURED_RUNS,
    paillier_key_size: int = DEFAULT_KEY_SIZE_BITS,
    rpc_url: str | None = None,
    confirmations: int = DEFAULT_CONFIRMATIONS,
    submission_mode: str = DEFAULT_SUBMISSION_MODE,
    show_progress: bool = False,
    seed: int = 42,
    buy_ratio: float = 0.5,
    min_quantity: int = 1,
    max_quantity: int = 1_000,
    min_price: float = 1_800.0,
    max_price: float = 2_200.0,
    symbol: str = "ETH-USD",
    trader_count: int = 25,
) -> pd.DataFrame:
    """Run Stage 8 and save Paillier/PHE + blockchain audit outputs."""
    if warmup_runs < 0:
        raise ValueError("warmup_runs must be zero or greater")
    if measured_runs <= 0:
        raise ValueError("measured_runs must be greater than zero")
    if paillier_key_size < 128:
        raise ValueError("paillier_key_size must be at least 128")
    if confirmations < 0:
        raise ValueError("confirmations must be zero or greater")
    if submission_mode not in SUBMISSION_MODES:
        raise ValueError(
            f"submission_mode must be one of: {', '.join(sorted(SUBMISSION_MODES))}"
        )
    if raw_runs_output_path == DEFAULT_RAW_RUNS_PATH and output_path != DEFAULT_RESULTS_PATH:
        raw_runs_output_path = Path(output_path).parent / "raw_runs.csv"
    if blockchain_audit_output_path == DEFAULT_AUDIT_PATH and output_path != DEFAULT_RESULTS_PATH:
        blockchain_audit_output_path = Path(output_path).parent / "blockchain_audit.csv"
    if (
        evidence_index_output_path == DEFAULT_EVIDENCE_INDEX_PATH
        and output_path != DEFAULT_RESULTS_PATH
    ):
        evidence_index_output_path = Path(output_path).parent / "encrypted_evidence_index.csv"
    if batch_evidence_dir == DEFAULT_BATCH_EVIDENCE_DIR and output_path != DEFAULT_RESULTS_PATH:
        batch_evidence_dir = Path(output_path).parent.parent / "batch_evidence"

    experiment_started_at = perf_counter()
    connection = connect_to_batch_audit(deployment_path, rpc_url=rpc_url)
    orders = load_or_generate_orders(
        input_path=input_path,
        batch_sizes=batch_sizes,
        seed=seed,
        buy_ratio=buy_ratio,
        min_quantity=min_quantity,
        max_quantity=max_quantity,
        min_price=min_price,
        max_price=max_price,
        symbol=symbol,
        trader_count=trader_count,
    )
    validated_orders = validate_orders(orders)
    manifest = write_dataset_manifest(validated_orders, seed=seed)
    manifest_rows = manifest_by_batch(manifest)
    public_key, private_key = generate_paillier_keypair(n_length=paillier_key_size)

    raw_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    evidence_index_rows: list[pd.DataFrame] = []
    batch_wall_clock_runtime_s: dict[str, float] = {}

    for _, batch_orders in validated_orders.groupby("batch_id", sort=True):
        batch_started_at = perf_counter()
        batch_id = str(batch_orders["batch_id"].iloc[0])
        batch_size = int(len(batch_orders))
        batch_manifest = manifest_rows[batch_id]
        if show_progress:
            print(f"Processing {batch_id} | batch size: {batch_size}", flush=True)

        for warmup_index in range(warmup_runs):
            phe_output = run_timed_paillier_batch(batch_orders, public_key, private_key)
            raw_rows.append(
                build_raw_run_row(
                    phe_output=phe_output,
                    run_id=f"warmup_{warmup_index + 1:04d}",
                    is_warmup=True,
                    seed=seed,
                    input_hash=str(batch_manifest["input_hash"]),
                )
            )
            del phe_output
            gc.collect()

        measured_outputs: list[dict[str, Any]] = []
        for _run_index in range(measured_runs):
            measured_outputs.append(
                run_timed_paillier_batch(batch_orders, public_key, private_key)
            )

        canonical_output = measured_outputs[0]
        evidence_started_at = perf_counter()
        _paths, evidence_hashes, evidence_index = write_encrypted_evidence_files(
            batch_orders=batch_orders,
            phe_output=canonical_output,
            public_key=public_key,
            key_size_bits=paillier_key_size,
            batch_evidence_dir=batch_evidence_dir,
        )
        evidence_write_runtime_s = perf_counter() - evidence_started_at
        evidence_index_rows.append(evidence_index)

        hashing_started_at = perf_counter()
        result_hash = build_paillier_blockchain_result_hash(
            batch_result=canonical_output["result"],
            public_key_hash=public_key_n_hash(public_key),
            evidence_hashes=evidence_hashes,
        )
        hashing_runtime_s = perf_counter() - hashing_started_at

        tx_result = record_paillier_batch_audit(
            connection=connection,
            batch_result=canonical_output["result"],
            evidence_hashes=evidence_hashes,
            result_hash=result_hash,
            confirmations=confirmations,
            submission_mode=submission_mode,
        )
        audit_rows.extend(tx_result.get("audit_rows", []))
        blockchain_runtime_s = float(tx_result["blockchain_transaction_runtime_ms"]) / 1_000

        for run_index, phe_output in enumerate(measured_outputs, start=1):
            raw_rows.append(
                build_raw_run_row(
                    phe_output=phe_output,
                    run_id=f"measured_{run_index:04d}",
                    is_warmup=False,
                    seed=seed,
                    input_hash=str(batch_manifest["input_hash"]),
                    evidence_write_runtime_s=evidence_write_runtime_s,
                    hashing_runtime_s=hashing_runtime_s,
                    blockchain_runtime_s=blockchain_runtime_s,
                    tx_result=tx_result,
                )
            )
        measured_outputs.clear()
        gc.collect()

        batch_wall_clock_runtime_s[batch_id] = perf_counter() - batch_started_at
        if show_progress:
            print(
                f"Completed {batch_id} | batch size: {batch_size} | "
                f"runtime: {batch_wall_clock_runtime_s[batch_id]:.2f} s",
                flush=True,
            )

    raw_runs = pd.DataFrame(raw_rows)
    canonical_raw_runs = raw_runs[RAW_RUN_COLUMNS]
    summary = summarize_measured_runs(
        canonical_raw_runs,
        experiment_name=PAILLIER_PHE_BLOCKCHAIN_VARIANT,
        variant=PAILLIER_PHE_BLOCKCHAIN_VARIANT,
        seed=seed,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )
    summary = apply_wall_clock_runtime_columns(
        summary,
        batch_wall_clock_runtime_s=batch_wall_clock_runtime_s,
        experiment_wall_clock_runtime_s=perf_counter() - experiment_started_at,
    )
    summary = add_common_summary_columns(summary, raw_runs)

    save_dataframe(raw_runs, raw_runs_output_path)
    save_dataframe(summary, output_path)
    save_dataframe(
        pd.DataFrame(audit_rows, columns=PAILLIER_BLOCKCHAIN_AUDIT_COLUMNS),
        blockchain_audit_output_path,
    )
    index = (
        pd.concat(evidence_index_rows, ignore_index=True)
        if evidence_index_rows
        else pd.DataFrame(columns=ENCRYPTED_EVIDENCE_INDEX_COLUMNS)
    )
    save_dataframe(index, evidence_index_output_path)
    return summary


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for Stage 8."""
    parser = argparse.ArgumentParser(
        description="Run Paillier/PHE encrypted aggregation with BatchAudit blockchain audit."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_SYNTHETIC_ORDERS_PATH)
    parser.add_argument("--deployment", type=Path, default=DEFAULT_DEPLOYMENT_PATH)
    parser.add_argument("--rpc-url", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--raw-runs-output", type=Path, default=DEFAULT_RAW_RUNS_PATH)
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument(
        "--evidence-index-output",
        type=Path,
        default=DEFAULT_EVIDENCE_INDEX_PATH,
    )
    parser.add_argument("--batch-evidence-dir", type=Path, default=DEFAULT_BATCH_EVIDENCE_DIR)
    parser.add_argument("--figures-dir", type=Path, default=DEFAULT_FIGURES_DIR)
    parser.add_argument("--batch-sizes", type=int, nargs="+", default=DEFAULT_EXPERIMENT_BATCH_SIZES)
    parser.add_argument("--warmup-runs", type=int, default=DEFAULT_WARMUP_RUNS)
    parser.add_argument("--measured-runs", type=int, default=DEFAULT_MEASURED_RUNS)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--confirmations", type=int, default=DEFAULT_CONFIRMATIONS)
    parser.add_argument("--submission-mode", choices=sorted(SUBMISSION_MODES), default=DEFAULT_SUBMISSION_MODE)
    parser.add_argument("--paillier-key-size", type=int, default=DEFAULT_KEY_SIZE_BITS)
    parser.add_argument("--buy-ratio", type=float, default=0.5)
    parser.add_argument("--min-quantity", type=int, default=1)
    parser.add_argument("--max-quantity", type=int, default=1_000)
    parser.add_argument("--min-price", type=float, default=1_800.0)
    parser.add_argument("--max-price", type=float, default=2_200.0)
    parser.add_argument("--symbol", default="ETH-USD")
    parser.add_argument("--trader-count", type=int, default=25)
    parser.add_argument("--skip-visualizations", action="store_true")
    parser.add_argument("--skip-final-comparison", action="store_true")
    parser.add_argument("--skip-cache-cleanup", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Run Stage 8 from command-line arguments."""
    command_started_at = perf_counter()
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    batch_sizes = tuple(args.batch_sizes) if args.batch_sizes is not None else None

    try:
        run_paillier_phe_blockchain_experiment(
            input_path=args.input,
            deployment_path=args.deployment,
            output_path=args.output,
            raw_runs_output_path=args.raw_runs_output,
            blockchain_audit_output_path=args.audit_output,
            evidence_index_output_path=args.evidence_index_output,
            batch_evidence_dir=args.batch_evidence_dir,
            batch_sizes=batch_sizes,
            warmup_runs=args.warmup_runs,
            measured_runs=args.measured_runs,
            paillier_key_size=args.paillier_key_size,
            rpc_url=args.rpc_url,
            confirmations=args.confirmations,
            submission_mode=args.submission_mode,
            show_progress=True,
            seed=args.seed,
            buy_ratio=args.buy_ratio,
            min_quantity=args.min_quantity,
            max_quantity=args.max_quantity,
            min_price=args.min_price,
            max_price=args.max_price,
            symbol=args.symbol,
            trader_count=args.trader_count,
        )

        if not args.skip_visualizations:
            create_paillier_phe_blockchain_visualizations(
                input_path=args.output,
                output_dir=args.figures_dir,
            )

        if not args.skip_final_comparison:
            refresh_final_comparison(infer_results_root(args.output))
    finally:
        if not args.skip_cache_cleanup:
            clean_python_caches()
        command_wall_clock_runtime_s = perf_counter() - command_started_at
        write_command_wall_clock_runtime(args.output, command_wall_clock_runtime_s)
        print(f"Full wall-clock runtime: {command_wall_clock_runtime_s:.3f}s", flush=True)


if __name__ == "__main__":
    main()
