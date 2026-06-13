from unittest.mock import MagicMock

import ccxt
import pytest

from src.utils.network import call_with_retries


def test_call_with_retries_succeeds_on_second_attempt() -> None:
    fn = MagicMock(side_effect=[ccxt.ExchangeNotAvailable("502"), "ok"])

    result = call_with_retries(fn, attempts=3, delay_sec=0)

    assert result == "ok"
    assert fn.call_count == 2


def test_call_with_retries_raises_non_transient_immediately() -> None:
    fn = MagicMock(side_effect=ValueError("bad"))

    with pytest.raises(ValueError, match="bad"):
        call_with_retries(fn, attempts=3, delay_sec=0)

    assert fn.call_count == 1
