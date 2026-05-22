from src.common.timing import time_call


def test_time_call_returns_result_and_elapsed_seconds() -> None:
    result, elapsed_seconds = time_call(lambda: "done")

    assert result == "done"
    assert elapsed_seconds >= 0
