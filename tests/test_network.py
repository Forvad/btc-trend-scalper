import ccxt
import requests

from src.utils.network import is_transient_network_error


def test_exchange_not_available_502_is_transient() -> None:
    exc = ccxt.ExchangeNotAvailable(
        "hyperliquid POST https://api.hyperliquid.xyz/info 502 Bad Gateway"
    )
    assert is_transient_network_error(exc) is True


def test_read_timeout_is_transient() -> None:
    exc = requests.exceptions.ReadTimeout("read timed out")
    assert is_transient_network_error(exc) is True


def test_http_502_error_is_transient() -> None:
    response = requests.Response()
    response.status_code = 502
    exc = requests.exceptions.HTTPError("502 Bad Gateway", response=response)
    assert is_transient_network_error(exc) is True


def test_timeout_error_is_transient() -> None:
    assert is_transient_network_error(TimeoutError("tick")) is True


def test_value_error_is_not_transient() -> None:
    assert is_transient_network_error(ValueError("bad config")) is False


def test_wrapped_read_timeout_is_transient() -> None:
    try:
        raise requests.exceptions.ReadTimeout("read timed out")
    except requests.exceptions.ReadTimeout as exc:
        wrapped = RuntimeError("ccxt failed")
        wrapped.__cause__ = exc
    assert is_transient_network_error(wrapped) is True
