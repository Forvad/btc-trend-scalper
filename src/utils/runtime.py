from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable, TypeVar

T = TypeVar("T")


def call_with_timeout(func: Callable[[], T], timeout_sec: float) -> T:
    """Выполняет func в отдельном потоке; при превышении timeout_sec — TimeoutError."""
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func)
        try:
            return future.result(timeout=timeout_sec)
        except FuturesTimeoutError as exc:
            raise TimeoutError(f"Operation timed out after {timeout_sec:.0f}s") from exc
