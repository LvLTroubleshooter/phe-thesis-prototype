"""Plaintext CLOB + blockchain audit experiment runner.

This variant runs CLOB matching as part of its own pipeline, then records
batch-level audit evidence on the reusable local BatchAudit contract.
"""

from __future__ import annotations

import json
import gc
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

import pandas as pd
from web3 import Web3

from src.common.file_hashing import (
    hex_digest_to_bytes32,
    sha256_file,
    sha256_mapping,
)
from src.common.metrics import (
    append_dataframe,
    calculate_throughput,
    reset_output_file,
    save_dataframe,
    seconds_to_milliseconds,
)
from src.common.timing import time_call
from src.common.research_outputs import (
    BLOCKCHAIN_AUDIT_COLUMNS,
    RAW_RUN_COLUMNS,
    apply_wall_clock_runtime_columns,
    result_hash_from_summary_row,
    summarize_measured_runs,
    utc_now_iso,
    write_dataset_manifest,
    manifest_by_batch,
)
from src.experiments.run_plaintext_baseline import (
    DEFAULT_EXPERIMENT_BATCH_SIZES,
    DEFAULT_MEASURED_RUNS,
    DEFAULT_WARMUP_RUNS,
    load_or_generate_orders,
)
from src.common.order_schema import validate_orders
from src.variants.plaintext.baseline import (
    TRADE_LOG_COLUMNS,
    UNMATCHED_ORDER_COLUMNS,
    match_plaintext_clob_batch,
)

PLAINTEXT_BLOCKCHAIN_VARIANT = "plaintext_blockchain"
DEFAULT_DEPLOYMENT_PATH = Path("blockchain/deployments/BatchAudit.localhost.json")
DEFAULT_ORDERS_PATH = Path("data/synthetic_orders.csv")
DEFAULT_BLOCKCHAIN_RESULTS_PATH = Path(
    "results/plaintext_blockchain/csv/batch_summary.csv"
)
DEFAULT_BLOCKCHAIN_RAW_RUNS_PATH = Path("results/plaintext_blockchain/csv/raw_runs.csv")
DEFAULT_BLOCKCHAIN_AUDIT_PATH = Path("results/plaintext_blockchain/csv/blockchain_audit.csv")
DEFAULT_BLOCKCHAIN_TRADES_PATH = Path(
    "results/plaintext_blockchain/csv/trades.csv"
)
DEFAULT_BLOCKCHAIN_UNMATCHED_ORDERS_PATH = Path(
    "results/plaintext_blockchain/csv/unmatched_orders.csv"
)
DEFAULT_BLOCKCHAIN_BATCH_EVIDENCE_DIR = Path(
    "results/plaintext_blockchain/batch_evidence"
)
DEFAULT_CONFIRMATIONS = 2
DEFAULT_SUBMISSION_MODE = "sequential"
SUBMISSION_MODES = {"sequential", "burst"}

BATCH_RECORD_FIELDS = {
    "variant": 0,
    "batchId": 1,
    "batchSize": 2,
    "buyVolume": 3,
    "sellVolume": 4,
    "matchedVolume": 5,
    "executedTradeCount": 6,
    "ordersFileHash": 7,
    "tradesFileHash": 8,
    "unmatchedOrdersFileHash": 9,
    "resultRowHash": 10,
    "submitter": 11,
    "recordedAt": 12,
    "recordedBlock": 13,
    "exists": 14,
}


@dataclass(frozen=True)
class BlockchainConnection:
    """Connection details for the deployed BatchAudit contract."""

    web3: Web3
    contract: Any
    deployment: dict[str, Any]
    account: str


def record_field(record: Any, field_name: str) -> Any:
    """Read a BatchRecord field from Web3 tuple or attribute-style output."""
    if hasattr(record, field_name):
        return getattr(record, field_name)
    return record[BATCH_RECORD_FIELDS[field_name]]


def bytes32_to_hex(value: Any) -> str:
    """Return a 64-character hex digest from bytes32-like Web3 values."""
    if isinstance(value, str):
        return value.removeprefix("0x")
    return value.hex().removeprefix("0x")


def load_deployment(deployment_path: str | Path = DEFAULT_DEPLOYMENT_PATH) -> dict[str, Any]:
    """Load BatchAudit deployment metadata."""
    path = Path(deployment_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Deployment file not found: {path}. "
            "Start Hardhat and deploy BatchAudit before running the plaintext + blockchain experiment."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def connect_to_batch_audit(
    deployment_path: str | Path = DEFAULT_DEPLOYMENT_PATH,
    rpc_url: str | None = None,
) -> BlockchainConnection:
    """Connect to the deployed BatchAudit contract."""
    deployment = load_deployment(deployment_path)
    endpoint = rpc_url or deployment["rpcUrl"]
    web3 = Web3(Web3.HTTPProvider(endpoint))
    if not web3.is_connected():
        raise ConnectionError(
            f"Could not connect to local blockchain RPC: {endpoint}. "
            "Start it with: cd blockchain && npx hardhat node"
        )

    chain_id = web3.eth.chain_id
    expected_chain_id = int(deployment["chainId"])
    if chain_id != expected_chain_id:
        raise ValueError(
            f"Connected to chain ID {chain_id}, expected {expected_chain_id}"
        )

    accounts = web3.eth.accounts
    if not accounts:
        raise RuntimeError("No unlocked local blockchain accounts are available")

    address = Web3.to_checksum_address(deployment["address"])
    contract = web3.eth.contract(address=address, abi=deployment["abi"])
    return BlockchainConnection(
        web3=web3,
        contract=contract,
        deployment=deployment,
        account=accounts[0],
    )


def compute_evidence_hashes(
    orders_path: str | Path = DEFAULT_ORDERS_PATH,
    trades_path: str | Path = DEFAULT_BLOCKCHAIN_TRADES_PATH,
    unmatched_orders_path: str | Path = DEFAULT_BLOCKCHAIN_UNMATCHED_ORDERS_PATH,
) -> dict[str, str]:
    """Hash the evidence files used by the blockchain audit layer."""
    paths = {
        "orders_file_hash": Path(orders_path),
        "trades_file_hash": Path(trades_path),
        "unmatched_orders_file_hash": Path(unmatched_orders_path),
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing plaintext + blockchain evidence files: " + ", ".join(missing))
    return {name: sha256_file(path) for name, path in paths.items()}


def compute_batch_evidence_hashes(
    orders_path: str | Path,
    trades_path: str | Path,
    unmatched_orders_path: str | Path,
) -> dict[str, str]:
    """Hash one batch's evidence files and expose simple column names."""
    hashes = compute_evidence_hashes(orders_path, trades_path, unmatched_orders_path)
    return {
        "input_hash": hashes["orders_file_hash"],
        "trades_hash": hashes["trades_file_hash"],
        "unmatched_hash": hashes["unmatched_orders_file_hash"],
        **hashes,
    }


def build_result_row_payload(row: pd.Series) -> dict[str, Any]:
    """Build the row payload that is hashed and audited on-chain."""
    return {
        "source_variant": PLAINTEXT_BLOCKCHAIN_VARIANT,
        "batch_id": row["batch_id"],
        "batch_size": int(row["batch_size"]),
        "buy_volume": int(row["buy_volume"]),
        "sell_volume": int(row["sell_volume"]),
        "matched_volume": int(row["matched_volume"]),
        "executed_trade_count": int(row["executed_trade_count"]),
    }


def build_result_row_hash(row: pd.Series) -> str:
    """Hash the stable batch-level result payload."""
    return sha256_mapping(build_result_row_payload(row))


def blockchain_record_matches(
    record: Any,
    row: pd.Series,
    hashes: dict[str, str],
    result_row_hash: str,
) -> bool:
    """Check that an on-chain record matches the off-chain evidence."""
    return (
        record_field(record, "variant") == PLAINTEXT_BLOCKCHAIN_VARIANT
        and record_field(record, "batchId") == str(row["batch_id"])
        and int(record_field(record, "batchSize")) == int(row["batch_size"])
        and int(record_field(record, "buyVolume")) == int(row["buy_volume"])
        and int(record_field(record, "sellVolume")) == int(row["sell_volume"])
        and int(record_field(record, "matchedVolume")) == int(row["matched_volume"])
        and int(record_field(record, "executedTradeCount")) == int(row["executed_trade_count"])
        and bytes32_to_hex(record_field(record, "ordersFileHash")) == hashes["orders_file_hash"]
        and bytes32_to_hex(record_field(record, "tradesFileHash")) == hashes["trades_file_hash"]
        and bytes32_to_hex(record_field(record, "unmatchedOrdersFileHash")) == hashes["unmatched_orders_file_hash"]
        and bytes32_to_hex(record_field(record, "resultRowHash")) == result_row_hash
    )


def block_timestamp(web3: Web3, block_number: int) -> int:
    """Return a block timestamp, or zero when the block is unavailable."""
    try:
        block = web3.eth.get_block(block_number)
    except Exception:
        return 0
    return int(block.get("timestamp", 0))


def block_metric(web3: Web3, block_number: int, name: str, default: int = 0) -> int:
    """Return an integer block metric, or a default when unavailable."""
    try:
        block = web3.eth.get_block(block_number)
    except Exception:
        return default
    value = block.get(name, default)
    return int(value) if value is not None else default


def transaction_metric(web3: Web3, transaction_hash: Any, name: str, default: int = 0) -> int:
    """Return an integer transaction metric, or a default when unavailable."""
    try:
        transaction = web3.eth.get_transaction(transaction_hash)
    except Exception:
        return default
    value = transaction.get(name, default)
    return int(value) if value is not None else default


def wait_for_confirmations(
    web3: Web3,
    receipt_block_number: int,
    confirmations: int,
    poll_interval_s: float = 1.0,
) -> int:
    """Wait until the requested confirmation depth is reached."""
    target_block = receipt_block_number + max(confirmations, 0)
    while web3.eth.block_number < target_block:
        sleep(poll_interval_s)
    return int(web3.eth.block_number)


def record_plaintext_batch_audit(
    connection: BlockchainConnection,
    row: pd.Series,
    hashes: dict[str, str],
    result_row_hash: str,
    confirmations: int = DEFAULT_CONFIRMATIONS,
    submission_mode: str = DEFAULT_SUBMISSION_MODE,
) -> dict[str, Any]:
    """Write or verify one plaintext + blockchain batch audit record on-chain."""
    if submission_mode not in SUBMISSION_MODES:
        raise ValueError(
            f"submission_mode must be one of: {', '.join(sorted(SUBMISSION_MODES))}"
        )
    contract = connection.contract
    web3 = connection.web3
    batch_id = str(row["batch_id"])

    if contract.functions.batchExists(PLAINTEXT_BLOCKCHAIN_VARIANT, batch_id).call():
        record = contract.functions.getBatchAudit(PLAINTEXT_BLOCKCHAIN_VARIANT, batch_id).call()
        correctness_pass = blockchain_record_matches(record, row, hashes, result_row_hash)
        return {
            "record_status": "already_exists",
            "correctness_pass": correctness_pass,
            "blockchain_transaction_runtime_ms": 0.0,
            "gas_used": 0,
            "transaction_hash": "",
            "block_number": int(record_field(record, "recordedBlock")),
            "effective_gas_price": 0,
            "submitter": record_field(record, "submitter"),
            "tx_submitted_at_wall_time": "",
            "tx_mined_at_wall_time": "",
            "tx_confirmed_at_wall_time": "",
            "tx_submission_time_s": 0.0,
            "tx_submission_to_mined_s": 0.0,
            "tx_mined_to_confirmed_s": 0.0,
            "tx_total_confirmation_s": 0.0,
            "pending_block_distance": 0,
            "included_block_number": int(record_field(record, "recordedBlock")),
            "confirmed_at_block_number": int(record_field(record, "recordedBlock")),
            "included_block_timestamp": 0,
            "confirmed_block_timestamp": 0,
            "base_fee_per_gas": 0,
            "max_fee_per_gas": 0,
            "max_priority_fee_per_gas": 0,
            "block_gas_limit": 0,
            "block_gas_used": 0,
            "block_gas_used_percent": 0.0,
            "transaction_index": 0,
            "nonce": 0,
            "target_confirmations": confirmations,
            "submission_mode": submission_mode,
            "revert_reason_if_failed": "",
        }

    function_call = contract.functions.recordBatchAudit(
        PLAINTEXT_BLOCKCHAIN_VARIANT,
        batch_id,
        int(row["batch_size"]),
        int(row["buy_volume"]),
        int(row["sell_volume"]),
        int(row["matched_volume"]),
        int(row["executed_trade_count"]),
        hex_digest_to_bytes32(hashes["orders_file_hash"]),
        hex_digest_to_bytes32(hashes["trades_file_hash"]),
        hex_digest_to_bytes32(hashes["unmatched_orders_file_hash"]),
        hex_digest_to_bytes32(result_row_hash),
    )

    tx_started_at = perf_counter()
    tx_submitted_at_wall_time = utc_now_iso()
    submitted_at_block_number = int(web3.eth.block_number)
    submit_started_at = perf_counter()
    tx_hash = function_call.transact({"from": connection.account})
    tx_submission_time_s = perf_counter() - submit_started_at

    receipt = web3.eth.wait_for_transaction_receipt(tx_hash)
    tx_mined_at_wall_time = utc_now_iso()
    mined_at = perf_counter()

    receipt_block_number = int(receipt["blockNumber"])
    confirmed_block_number = wait_for_confirmations(
        web3,
        receipt_block_number,
        confirmations,
    )
    tx_confirmed_at_wall_time = utc_now_iso()
    tx_total_confirmation_s = perf_counter() - tx_started_at
    tx_submission_to_mined_s = mined_at - tx_started_at
    tx_mined_to_confirmed_s = tx_total_confirmation_s - tx_submission_to_mined_s

    included_block_timestamp = block_timestamp(web3, receipt_block_number)
    confirmed_block_timestamp = block_timestamp(web3, confirmed_block_number)
    block_gas_limit = block_metric(web3, receipt_block_number, "gasLimit")
    block_gas_used = block_metric(web3, receipt_block_number, "gasUsed")
    base_fee_per_gas = block_metric(web3, receipt_block_number, "baseFeePerGas")
    max_fee_per_gas = transaction_metric(web3, tx_hash, "maxFeePerGas")
    max_priority_fee_per_gas = transaction_metric(web3, tx_hash, "maxPriorityFeePerGas")
    record = contract.functions.getBatchAudit(PLAINTEXT_BLOCKCHAIN_VARIANT, batch_id).call()
    correctness_pass = blockchain_record_matches(record, row, hashes, result_row_hash)
    status_code = int(receipt.get("status", 0))

    return {
        "record_status": "recorded" if status_code == 1 else "failed",
        "correctness_pass": correctness_pass,
        "blockchain_transaction_runtime_ms": seconds_to_milliseconds(tx_total_confirmation_s),
        "gas_used": int(receipt["gasUsed"]),
        "transaction_hash": receipt["transactionHash"].hex(),
        "block_number": receipt_block_number,
        "effective_gas_price": int(receipt.get("effectiveGasPrice", 0)),
        "submitter": connection.account,
        "tx_submitted_at_wall_time": tx_submitted_at_wall_time,
        "tx_mined_at_wall_time": tx_mined_at_wall_time,
        "tx_confirmed_at_wall_time": tx_confirmed_at_wall_time,
        "tx_submission_time_s": tx_submission_time_s,
        "tx_submission_to_mined_s": tx_submission_to_mined_s,
        "tx_mined_to_confirmed_s": tx_mined_to_confirmed_s,
        "tx_total_confirmation_s": tx_total_confirmation_s,
        "pending_block_distance": max(receipt_block_number - submitted_at_block_number, 0),
        "included_block_number": receipt_block_number,
        "confirmed_at_block_number": confirmed_block_number,
        "included_block_timestamp": included_block_timestamp,
        "confirmed_block_timestamp": confirmed_block_timestamp,
        "base_fee_per_gas": base_fee_per_gas,
        "max_fee_per_gas": max_fee_per_gas,
        "max_priority_fee_per_gas": max_priority_fee_per_gas,
        "block_gas_limit": block_gas_limit,
        "block_gas_used": block_gas_used,
        "block_gas_used_percent": (block_gas_used / block_gas_limit * 100)
        if block_gas_limit
        else 0.0,
        "transaction_index": int(receipt.get("transactionIndex", 0)),
        "nonce": transaction_metric(web3, tx_hash, "nonce"),
        "target_confirmations": confirmations,
        "submission_mode": submission_mode,
        "revert_reason_if_failed": "" if status_code == 1 else "transaction reverted",
    }


def batch_trade_volume_matches(results: pd.DataFrame, trades: pd.DataFrame) -> dict[str, bool]:
    """Check matched volume against the trade log for every batch."""
    if trades.empty:
        trade_sums: dict[str, int] = {}
    else:
        trade_sums = (
            trades.groupby("batch_id")["executed_quantity"].sum().astype(int).to_dict()
        )
    checks: dict[str, bool] = {}
    for _, row in results.iterrows():
        batch_id = str(row["batch_id"])
        checks[batch_id] = int(row["matched_volume"]) == int(trade_sums.get(batch_id, 0))
    return checks


def build_plaintext_blockchain_raw_run_row(
    result: dict[str, Any],
    trades: pd.DataFrame,
    unmatched_orders: pd.DataFrame,
    run_id: str,
    is_warmup: bool,
    seed: int,
    input_hash: str,
    matching_runtime_s: float,
    evidence_write_runtime_s: float,
    hashing_runtime_s: float,
    blockchain_runtime_s: float,
    tx_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build one plaintext + blockchain raw run row."""
    n_orders = int(result["n_orders"])
    total_runtime_s = (
        matching_runtime_s
        + evidence_write_runtime_s
        + hashing_runtime_s
        + blockchain_runtime_s
    )
    matched_volume = int(result["matched_volume"])
    trade_volume = int(trades["executed_quantity"].sum()) if not trades.empty else 0
    return {
        "experiment_name": PLAINTEXT_BLOCKCHAIN_VARIANT,
        "variant": PLAINTEXT_BLOCKCHAIN_VARIANT,
        "batch_id": result["batch_id"],
        "batch_size": n_orders,
        "run_id": run_id,
        "is_warmup": is_warmup,
        "seed": seed,
        "input_hash": input_hash,
        "matching_runtime_s": matching_runtime_s,
        "encryption_runtime_s": 0.0,
        "encrypted_computation_runtime_s": 0.0,
        "decryption_runtime_s": 0.0,
        "evidence_write_runtime_s": evidence_write_runtime_s,
        "hashing_runtime_s": hashing_runtime_s,
        "blockchain_runtime_s": blockchain_runtime_s,
        "total_runtime_s": total_runtime_s,
        "throughput_orders_per_second": calculate_throughput(n_orders, total_runtime_s),
        "matched_volume": matched_volume,
        "matched_trades_count": int(result["executed_trade_count"]),
        "unmatched_orders_count": len(unmatched_orders),
        "correctness_pass": matched_volume == trade_volume and bool(tx_result["correctness_pass"]) if tx_result else matched_volume == trade_volume,
        "blockchain_tx_count": 1 if tx_result and tx_result["transaction_hash"] else 0,
        "blockchain_gas_used_total": int(tx_result["gas_used"]) if tx_result else 0,
        "blockchain_block_number": int(tx_result["block_number"]) if tx_result else 0,
        "blockchain_transaction_hash": tx_result["transaction_hash"] if tx_result else "",
        "created_at": utc_now_iso(),
    }


def build_plaintext_blockchain_metric_row(
    metric: dict[str, Any],
    run_id: str,
    seed: int,
    input_hash: str,
    evidence_write_runtime_s: float,
    hashing_runtime_s: float,
    blockchain_runtime_s: float,
    tx_result: dict[str, Any],
) -> dict[str, Any]:
    """Build one small raw-run row without retaining large log DataFrames."""
    n_orders = int(metric["n_orders"])
    total_runtime_s = (
        float(metric["matching_runtime_s"])
        + evidence_write_runtime_s
        + hashing_runtime_s
        + blockchain_runtime_s
    )
    return {
        "experiment_name": PLAINTEXT_BLOCKCHAIN_VARIANT,
        "variant": PLAINTEXT_BLOCKCHAIN_VARIANT,
        "batch_id": metric["batch_id"],
        "batch_size": n_orders,
        "run_id": run_id,
        "is_warmup": False,
        "seed": seed,
        "input_hash": input_hash,
        "matching_runtime_s": float(metric["matching_runtime_s"]),
        "encryption_runtime_s": 0.0,
        "encrypted_computation_runtime_s": 0.0,
        "decryption_runtime_s": 0.0,
        "evidence_write_runtime_s": evidence_write_runtime_s,
        "hashing_runtime_s": hashing_runtime_s,
        "blockchain_runtime_s": blockchain_runtime_s,
        "total_runtime_s": total_runtime_s,
        "throughput_orders_per_second": calculate_throughput(n_orders, total_runtime_s),
        "matched_volume": int(metric["matched_volume"]),
        "matched_trades_count": int(metric["executed_trade_count"]),
        "unmatched_orders_count": int(metric["unmatched_orders_count"]),
        "correctness_pass": bool(metric["correctness_pass"])
        and bool(tx_result["correctness_pass"]),
        "blockchain_tx_count": 1 if tx_result["transaction_hash"] else 0,
        "blockchain_gas_used_total": int(tx_result["gas_used"]),
        "blockchain_block_number": int(tx_result["block_number"]),
        "blockchain_transaction_hash": tx_result["transaction_hash"],
        "created_at": utc_now_iso(),
    }


def run_plaintext_blockchain_audit(
    input_path: str | Path = DEFAULT_ORDERS_PATH,
    deployment_path: str | Path = DEFAULT_DEPLOYMENT_PATH,
    output_path: str | Path = DEFAULT_BLOCKCHAIN_RESULTS_PATH,
    raw_runs_output_path: str | Path = DEFAULT_BLOCKCHAIN_RAW_RUNS_PATH,
    blockchain_audit_output_path: str | Path = DEFAULT_BLOCKCHAIN_AUDIT_PATH,
    trades_output_path: str | Path = DEFAULT_BLOCKCHAIN_TRADES_PATH,
    unmatched_orders_output_path: str | Path = DEFAULT_BLOCKCHAIN_UNMATCHED_ORDERS_PATH,
    batch_sizes: tuple[int, ...] | None = DEFAULT_EXPERIMENT_BATCH_SIZES,
    warmup_runs: int = DEFAULT_WARMUP_RUNS,
    measured_runs: int = DEFAULT_MEASURED_RUNS,
    rpc_url: str | None = None,
    show_progress: bool = False,
    seed: int = 42,
    buy_ratio: float = 0.5,
    min_quantity: int = 1,
    max_quantity: int = 1_000,
    min_price: float = 1_800.0,
    max_price: float = 2_200.0,
    symbol: str = "ETH-USD",
    trader_count: int = 25,
    confirmations: int = DEFAULT_CONFIRMATIONS,
    submission_mode: str = DEFAULT_SUBMISSION_MODE,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run full plaintext CLOB + blockchain audit experiment."""
    if confirmations < 0:
        raise ValueError("confirmations must be zero or greater")
    if submission_mode not in SUBMISSION_MODES:
        raise ValueError(
            f"submission_mode must be one of: {', '.join(sorted(SUBMISSION_MODES))}"
        )
    experiment_started_at = perf_counter()
    if raw_runs_output_path == DEFAULT_BLOCKCHAIN_RAW_RUNS_PATH and output_path != DEFAULT_BLOCKCHAIN_RESULTS_PATH:
        raw_runs_output_path = Path(output_path).parent / "raw_runs.csv"
    if blockchain_audit_output_path == DEFAULT_BLOCKCHAIN_AUDIT_PATH and output_path != DEFAULT_BLOCKCHAIN_RESULTS_PATH:
        blockchain_audit_output_path = Path(output_path).parent / "blockchain_audit.csv"
    connection = connect_to_batch_audit(deployment_path, rpc_url=rpc_url)
    orders, _data_loading_seconds = time_call(
        lambda: load_or_generate_orders(
            input_path=Path(input_path),
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
    )
    validated_orders = validate_orders(orders)
    manifest = write_dataset_manifest(validated_orders, seed=seed)
    manifest_rows = manifest_by_batch(manifest)
    batch_evidence_dir = Path(DEFAULT_BLOCKCHAIN_BATCH_EVIDENCE_DIR)
    raw_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    collect_return_logs = len(validated_orders) <= 100_000
    trade_outputs: list[pd.DataFrame] = []
    unmatched_outputs: list[pd.DataFrame] = []
    reset_output_file(trades_output_path)
    reset_output_file(unmatched_orders_output_path)
    trade_header_pending = True
    unmatched_header_pending = True
    batch_wall_clock_runtime_s: dict[str, float] = {}

    for _, batch_orders in validated_orders.groupby("batch_id", sort=True):
        batch_started_at = perf_counter()
        batch_id = str(batch_orders["batch_id"].iloc[0])
        batch_size = int(len(batch_orders))
        batch_manifest = manifest_rows[batch_id]
        if show_progress:
            print(
                f"Processing {batch_id} | batch size: {batch_size}",
                flush=True,
            )

        for warmup_index in range(warmup_runs):
            clob_output, runtime_seconds = time_call(
                lambda batch_orders=batch_orders: match_plaintext_clob_batch(batch_orders)
            )
            result, trades, unmatched_orders = clob_output
            raw_rows.append(
                build_plaintext_blockchain_raw_run_row(
                    result=result,
                    trades=trades,
                    unmatched_orders=unmatched_orders,
                    run_id=f"warmup_{warmup_index + 1:04d}",
                    is_warmup=True,
                    seed=seed,
                    input_hash=str(batch_manifest["input_hash"]),
                    matching_runtime_s=runtime_seconds,
                    evidence_write_runtime_s=0.0,
                    hashing_runtime_s=0.0,
                    blockchain_runtime_s=0.0,
                    tx_result=None,
                )
            )
            del clob_output, result, trades, unmatched_orders
            gc.collect()

        canonical_result: dict[str, Any] | None = None
        batch_trades: pd.DataFrame | None = None
        batch_unmatched: pd.DataFrame | None = None
        measured_metrics: list[dict[str, Any]] = []
        for run_index in range(measured_runs):
            clob_output, runtime_seconds = time_call(
                lambda batch_orders=batch_orders: match_plaintext_clob_batch(
                    batch_orders
                )
            )
            result, trades, unmatched = clob_output
            matched_volume = int(result["matched_volume"])
            trade_volume = int(trades["executed_quantity"].sum()) if not trades.empty else 0
            measured_metrics.append(
                {
                    "batch_id": result["batch_id"],
                    "n_orders": int(result["n_orders"]),
                    "buy_volume": int(result["buy_volume"]),
                    "sell_volume": int(result["sell_volume"]),
                    "matched_volume": matched_volume,
                    "executed_trade_count": int(result["executed_trade_count"]),
                    "unmatched_orders_count": len(unmatched),
                    "matching_runtime_s": runtime_seconds,
                    "correctness_pass": matched_volume == trade_volume,
                }
            )

            if run_index == 0:
                canonical_result = dict(result)
                batch_trades = trades
                batch_unmatched = unmatched
            else:
                del trades, unmatched
            del clob_output, result
            gc.collect()

        if canonical_result is None or batch_trades is None or batch_unmatched is None:
            raise RuntimeError("No measured CLOB output was produced")

        batch_orders_path = batch_evidence_dir / f"{batch_id}_orders.csv"
        batch_trades_path = batch_evidence_dir / f"{batch_id}_trades.csv"
        batch_unmatched_path = batch_evidence_dir / f"{batch_id}_unmatched_orders.csv"

        _, evidence_write_runtime_s = time_call(
            lambda: (
                save_dataframe(batch_orders, batch_orders_path),
                save_dataframe(batch_trades, batch_trades_path),
                save_dataframe(batch_unmatched, batch_unmatched_path),
                append_dataframe(
                    batch_trades,
                    trades_output_path,
                    include_header=trade_header_pending,
                ),
                append_dataframe(
                    batch_unmatched,
                    unmatched_orders_output_path,
                    include_header=unmatched_header_pending,
                ),
            )
        )
        trade_header_pending = False
        unmatched_header_pending = False
        if collect_return_logs:
            trade_outputs.append(batch_trades.copy())
            unmatched_outputs.append(batch_unmatched.copy())
        hashes, hashing_runtime_s = time_call(
            lambda: compute_batch_evidence_hashes(
                batch_orders_path,
                batch_trades_path,
                batch_unmatched_path,
            )
        )

        blockchain_row = pd.Series(
            {
                "variant": PLAINTEXT_BLOCKCHAIN_VARIANT,
                "batch_id": canonical_result["batch_id"],
                "batch_size": int(canonical_result["n_orders"]),
                "buy_volume": int(canonical_result["buy_volume"]),
                "sell_volume": int(canonical_result["sell_volume"]),
                "matched_volume": int(canonical_result["matched_volume"]),
                "executed_trade_count": int(canonical_result["executed_trade_count"]),
            }
        )
        blockchain_row["variant"] = PLAINTEXT_BLOCKCHAIN_VARIANT
        result_row_hash = build_result_row_hash(blockchain_row)
        tx_result = record_plaintext_batch_audit(
            connection=connection,
            row=blockchain_row,
            hashes=hashes,
            result_row_hash=result_row_hash,
            confirmations=confirmations,
            submission_mode=submission_mode,
        )

        blockchain_runtime_s = float(tx_result["blockchain_transaction_runtime_ms"]) / 1_000
        n_orders = int(canonical_result["n_orders"])
        matched_volume = int(canonical_result["matched_volume"])
        trade_volume_matches = (
            int(batch_trades["executed_quantity"].sum()) if not batch_trades.empty else 0
        ) == matched_volume
        internal_correctness_pass = (
            trade_volume_matches
            and int(canonical_result["buy_volume"]) >= 0
            and int(canonical_result["sell_volume"]) >= 0
            and matched_volume >= 0
        )
        correctness_pass = internal_correctness_pass and bool(tx_result["correctness_pass"])

        for run_index, metric in enumerate(measured_metrics, start=1):
            metric["correctness_pass"] = bool(metric["correctness_pass"]) and correctness_pass
            raw_rows.append(
                build_plaintext_blockchain_metric_row(
                    metric=metric,
                    run_id=f"measured_{run_index:04d}",
                    seed=seed,
                    input_hash=hashes["input_hash"],
                    evidence_write_runtime_s=evidence_write_runtime_s,
                    hashing_runtime_s=hashing_runtime_s,
                    blockchain_runtime_s=blockchain_runtime_s,
                    tx_result=tx_result,
                )
            )
        result_hash = build_result_row_hash(blockchain_row)
        evidence_root_hash = sha256_mapping(
            {
                "input_hash": hashes["input_hash"],
                "trades_hash": hashes["trades_hash"],
                "unmatched_hash": hashes["unmatched_hash"],
                "result_hash": result_hash,
            }
        )
        audit_rows.append(
            {
                "experiment_name": PLAINTEXT_BLOCKCHAIN_VARIANT,
                "variant": PLAINTEXT_BLOCKCHAIN_VARIANT,
                "batch_id": canonical_result["batch_id"],
                "batch_size": n_orders,
                "input_hash": hashes["input_hash"],
                "trades_hash": hashes["trades_hash"],
                "unmatched_hash": hashes["unmatched_hash"],
                "result_hash": result_hash,
                "evidence_root_hash": evidence_root_hash,
                "contract_address": connection.deployment["address"],
                "transaction_hash": tx_result["transaction_hash"],
                "block_number": tx_result["block_number"],
                "gas_used": tx_result["gas_used"],
                "transaction_time_s": blockchain_runtime_s,
                "confirmation_time_s": tx_result.get(
                    "tx_mined_to_confirmed_s",
                    blockchain_runtime_s,
                ),
                "tx_submitted_at_wall_time": tx_result.get("tx_submitted_at_wall_time", ""),
                "tx_mined_at_wall_time": tx_result.get("tx_mined_at_wall_time", ""),
                "tx_confirmed_at_wall_time": tx_result.get("tx_confirmed_at_wall_time", ""),
                "tx_submission_time_s": tx_result.get("tx_submission_time_s", 0.0),
                "tx_submission_to_mined_s": tx_result.get("tx_submission_to_mined_s", 0.0),
                "tx_mined_to_confirmed_s": tx_result.get("tx_mined_to_confirmed_s", 0.0),
                "tx_total_confirmation_s": tx_result.get(
                    "tx_total_confirmation_s",
                    blockchain_runtime_s,
                ),
                "pending_block_distance": tx_result.get("pending_block_distance", 0),
                "included_block_number": tx_result.get("included_block_number", tx_result["block_number"]),
                "confirmed_at_block_number": tx_result.get(
                    "confirmed_at_block_number",
                    tx_result["block_number"],
                ),
                "included_block_timestamp": tx_result.get("included_block_timestamp", 0),
                "confirmed_block_timestamp": tx_result.get("confirmed_block_timestamp", 0),
                "base_fee_per_gas": tx_result.get("base_fee_per_gas", 0),
                "max_fee_per_gas": tx_result.get("max_fee_per_gas", 0),
                "max_priority_fee_per_gas": tx_result.get("max_priority_fee_per_gas", 0),
                "effective_gas_price": tx_result.get("effective_gas_price", 0),
                "block_gas_limit": tx_result.get("block_gas_limit", 0),
                "block_gas_used": tx_result.get("block_gas_used", 0),
                "block_gas_used_percent": tx_result.get("block_gas_used_percent", 0.0),
                "transaction_index": tx_result.get("transaction_index", 0),
                "nonce": tx_result.get("nonce", 0),
                "target_confirmations": tx_result.get("target_confirmations", confirmations),
                "submission_mode": tx_result.get("submission_mode", submission_mode),
                "revert_reason_if_failed": tx_result.get("revert_reason_if_failed", ""),
                "status": "success" if correctness_pass else "failed",
                "created_at": utc_now_iso(),
            }
        )
        batch_wall_clock_runtime_s[batch_id] = perf_counter() - batch_started_at
        del batch_trades
        del batch_unmatched
        del canonical_result
        gc.collect()
        if show_progress:
            print(
                f"Completed {batch_id} | batch size: {batch_size} | "
                f"runtime: {batch_wall_clock_runtime_s[batch_id]:.2f} s",
                flush=True,
            )

    raw_runs = pd.DataFrame(raw_rows, columns=RAW_RUN_COLUMNS)
    results = summarize_measured_runs(
        raw_runs,
        experiment_name=PLAINTEXT_BLOCKCHAIN_VARIANT,
        variant=PLAINTEXT_BLOCKCHAIN_VARIANT,
        seed=seed,
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
    )
    save_dataframe(raw_runs, raw_runs_output_path)
    save_dataframe(
        pd.DataFrame(audit_rows, columns=BLOCKCHAIN_AUDIT_COLUMNS),
        blockchain_audit_output_path,
    )
    trades = (
        pd.concat(trade_outputs, ignore_index=True)
        if trade_outputs
        else pd.DataFrame(columns=TRADE_LOG_COLUMNS)
    )
    unmatched_orders = (
        pd.concat(unmatched_outputs, ignore_index=True)
        if unmatched_outputs
        else pd.DataFrame(columns=UNMATCHED_ORDER_COLUMNS)
    )
    if trade_header_pending:
        save_dataframe(pd.DataFrame(columns=TRADE_LOG_COLUMNS), trades_output_path)
    if unmatched_header_pending:
        save_dataframe(
            pd.DataFrame(columns=UNMATCHED_ORDER_COLUMNS),
            unmatched_orders_output_path,
        )
    results = apply_wall_clock_runtime_columns(
        results,
        batch_wall_clock_runtime_s=batch_wall_clock_runtime_s,
        experiment_wall_clock_runtime_s=perf_counter() - experiment_started_at,
    )
    save_dataframe(results, output_path)
    return results, trades, unmatched_orders
