import pandas as pd

from src.common.metrics import (
    COMMON_RESULT_COLUMNS,
    apply_common_result_schema,
    calculate_throughput,
    file_size_bytes,
    save_dataframe,
    seconds_to_milliseconds,
)


def test_calculate_throughput_handles_positive_runtime() -> None:
    assert calculate_throughput(100, 0.5) == 200


def test_calculate_throughput_handles_zero_runtime() -> None:
    assert calculate_throughput(100, 0) == 0


def test_seconds_to_milliseconds() -> None:
    assert seconds_to_milliseconds(1.5) == 1500


def test_save_dataframe_creates_parent_directory(tmp_path) -> None:
    output_path = tmp_path / "nested" / "results.csv"

    save_dataframe(pd.DataFrame([{"value": 1}]), output_path)

    assert output_path.exists()


def test_file_size_bytes_returns_zero_for_missing_file(tmp_path) -> None:
    assert file_size_bytes(tmp_path / "missing.csv") == 0


def test_apply_common_result_schema_adds_ablation_columns() -> None:
    result = apply_common_result_schema(
        pd.DataFrame([{"variant": "plaintext", "batch_id": "batch_0001"}])
    )

    assert result.columns[: len(COMMON_RESULT_COLUMNS)].tolist() == COMMON_RESULT_COLUMNS
    assert "blockchain_time_ms" in result.columns
    assert result.iloc[0]["blockchain_time_ms"] == 0
    assert result.iloc[0]["transaction_hash"] == ""
    assert result.iloc[0]["correctness_pass"] == False
