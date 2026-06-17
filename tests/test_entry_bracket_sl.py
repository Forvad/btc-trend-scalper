from unittest.mock import MagicMock, patch

import pytest

from src.config import AppConfig, ExchangeConfig, LiveConfig
from src.live.trader import LiveTrader


@patch("src.live.trader.has_credentials", return_value=False)
@patch("src.live.trader.create_public_exchange")
@patch("src.live.trader.create_hyperliquid_exchange")
@patch("src.live.trader.fetch_available_usdc", return_value=105.0)
def test_open_position_skips_when_bracket_sl_invalid(
    _mock_bal, _mock_hl, _mock_pub, _mock_creds
) -> None:
    config = AppConfig()
    config.exchange = ExchangeConfig(symbol="HYPE/USDC:USDC")
    config.live = LiveConfig(place_bracket_orders=True)
    trader = LiveTrader(config, timeframe="1h", dry_run=True)

    signal = {
        "close": 73.0,
        "supertrend": 72.31,
        "bb_upper": 80.0,
        "bb_lower": 66.5,
    }
    trader._place_market = MagicMock()

    opened = trader._open_position("short", signal)

    assert opened is False
    trader._place_market.assert_not_called()


@patch("src.live.trader.has_credentials", return_value=False)
@patch("src.live.trader.create_public_exchange")
@patch("src.live.trader.create_hyperliquid_exchange")
@patch("src.live.trader.fetch_available_usdc", return_value=105.0)
def test_open_position_proceeds_when_bracket_sl_valid(
    _mock_bal, _mock_hl, _mock_pub, _mock_creds
) -> None:
    config = AppConfig()
    config.exchange = ExchangeConfig(symbol="HYPE/USDC:USDC")
    config.live = LiveConfig(place_bracket_orders=True)
    trader = LiveTrader(config, timeframe="1h", dry_run=True)
    trader.exchange = MagicMock()
    trader.exchange.price_to_precision = lambda _s, p: p
    trader.exchange.market.return_value = {"limits": {"amount": {"min": 0.0}}}
    trader.exchange.amount_to_precision = lambda _s, a: a

    signal = {
        "close": 74.0,
        "supertrend": 75.5,
        "bb_upper": 80.0,
        "bb_lower": 66.5,
    }
    trader._place_market = MagicMock(return_value={"id": "1"})
    trader._get_balances = MagicMock(return_value=(100.0, 100.0))
    trader.notifier = MagicMock()

    opened = trader._open_position("short", signal)

    assert opened is True
    trader._place_market.assert_called_once()
