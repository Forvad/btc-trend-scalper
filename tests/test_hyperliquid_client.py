from unittest.mock import MagicMock

import ccxt

from src.exchange.hyperliquid_client import _load_markets


def test_load_markets_retries_on_502() -> None:
    exchange = MagicMock()
    exchange.load_markets.side_effect = [
        ccxt.ExchangeNotAvailable("502 Bad Gateway"),
        ccxt.ExchangeNotAvailable("502 Bad Gateway"),
        None,
    ]

    _load_markets(exchange)

    assert exchange.load_markets.call_count == 3
