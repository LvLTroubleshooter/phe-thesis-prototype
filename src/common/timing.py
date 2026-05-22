"""Shared timing helpers for prototype experiments."""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import TypeVar

T = TypeVar("T")


def time_call(function: Callable[[], T]) -> tuple[T, float]:
    """Run a zero-argument function and return its result with elapsed seconds."""
    started_at = perf_counter()
    result = function()
    return result, perf_counter() - started_at
