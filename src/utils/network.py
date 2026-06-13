from __future__ import annotations

import ccxt
import requests


def is_transient_network_error(exc: BaseException) -> bool:
    """Временные сбои сети/API — бот продолжит на следующем тике."""
    transient_types: tuple[type[BaseException], ...] = (
        TimeoutError,
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        ccxt.NetworkError,
        ccxt.RequestTimeout,
        ccxt.ExchangeNotAvailable,
    )
    if isinstance(exc, transient_types):
        return True
    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, transient_types):
            return True
        cause = cause.__cause__
    return False
