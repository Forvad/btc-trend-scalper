from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

import ccxt
import requests

T = TypeVar("T")

_TRANSIENT_TYPES: tuple[type[BaseException], ...] = (
    TimeoutError,
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    ccxt.NetworkError,
    ccxt.RequestTimeout,
    ccxt.ExchangeNotAvailable,
    ccxt.DDoSProtection,
)

_TRANSIENT_MARKERS = (
    "502",
    "503",
    "504",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "temporarily unavailable",
)


def _iter_exception_chain(exc: BaseException):
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__


def is_transient_network_error(exc: BaseException) -> bool:
    """Временные сбои сети/API — бот продолжит на следующем тике."""
    for err in _iter_exception_chain(exc):
        if isinstance(err, _TRANSIENT_TYPES):
            return True
        if isinstance(err, requests.exceptions.HTTPError) and err.response is not None:
            if err.response.status_code >= 500:
                return True
        if isinstance(err, ccxt.ExchangeError):
            msg = str(err).lower()
            if any(marker in msg for marker in _TRANSIENT_MARKERS):
                return True
    return False


def call_with_retries(
    func: Callable[[], T],
    *,
    attempts: int = 3,
    delay_sec: float = 2.0,
) -> T:
    """Повторяет вызов при временных сбоях API (502/timeout и т.п.)."""
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if not is_transient_network_error(exc) or attempt >= attempts - 1:
                raise
            time.sleep(delay_sec * (attempt + 1))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("call_with_retries: no attempts made")
