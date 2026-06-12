from unittest.mock import MagicMock, patch

import pytest

from src.config import AppConfig, ExchangeConfig, LiveConfig
from src.live.trader import LivePosition, LiveTrader


@patch("src.live.trader.create_public_exchange")
@patch("src.live.trader.create_hyperliquid_exchange")
def test_market_order_passes_reference_price(_mock_hl, _mock_pub) -> None:
    config = AppConfig()
    config.exchange = ExchangeConfig(symbol="HYPE/USDC:USDC")
    config.live = LiveConfig(slippage=0.001)
    trader = LiveTrader(config, timeframe="15m", dry_run=False)
    trader.exchange = MagicMock()
    trader.exchange.price_to_precision = lambda _symbol, price: price
    trader.exchange.create_order.return_value = {"id": "1"}

    trader.exchange.fetch_ticker.return_value = {"last": 42.5}
    trader.exchange.amount_to_precision = lambda _s, a: a
    trader.exchange.market.return_value = {"limits": {"amount": {"min": 0.0}}}

    trader._place_market("sell", 1.57, label="OPEN SHORT")

    trader.exchange.create_order.assert_called_once_with(
        "HYPE/USDC:USDC",
        "market",
        "sell",
        1.57,
        42.5,
        params={"slippage": "0.001"},
    )


@patch("src.live.trader.fetch_ohlcv")
@patch("src.live.trader.create_public_exchange")
@patch("src.live.trader.create_hyperliquid_exchange")
def test_tick_skips_signal_exit_when_brackets_enabled(
    _mock_hl, _mock_pub, mock_fetch
) -> None:
    config = AppConfig()
    config.exchange = ExchangeConfig(symbol="HYPE/USDC:USDC")
    config.live = LiveConfig(place_bracket_orders=True)
    trader = LiveTrader(config, timeframe="1h", dry_run=True)
    trader.exchange = MagicMock()

    pos = LivePosition(side="long", amount=1.0, entry_price=50.0)
    signal = {
        "timestamp": None,
        "close": 55.0,
        "long_exit_tp": True,
        "long_exit_stop": False,
        "short_exit_tp": False,
        "short_exit_stop": False,
        "bb_upper": 56.0,
        "supertrend": 48.0,
    }
    mock_fetch.return_value = MagicMock()
    trader._fetch_htf = MagicMock(return_value=None)
    trader.strategy.latest_signal = MagicMock(return_value=signal)
    trader._get_exchange_position = MagicMock(return_value=pos)
    trader._close_position = MagicMock()
    trader._manage_bracket_orders = MagicMock(return_value=None)

    result = trader.tick()

    trader._close_position.assert_not_called()
    trader._manage_bracket_orders.assert_called_once_with(pos, signal)
    assert result["action"] == "hold"


@patch("src.live.trader.create_public_exchange")
@patch("src.live.trader.create_hyperliquid_exchange")
@patch("src.live.trader.fetch_available_usdc", return_value=105.0)
def test_calc_order_amount_with_leverage_sizing(_mock_bal, _mock_hl, _mock_pub) -> None:
    config = AppConfig()
    config.exchange = ExchangeConfig(symbol="HYPE/USDC:USDC")
    config.live = LiveConfig(
        position_size_pct=0.95,
        use_leverage_for_sizing=True,
        leverage=5,
        max_notional_usd=200,
        min_notional_usd=50,
    )
    trader = LiveTrader(config, timeframe="1h", dry_run=False)
    trader.exchange = MagicMock()
    trader.exchange.amount_to_precision = lambda _s, a: a

    amount = trader._calc_order_amount(50.0)
    assert amount == pytest.approx(4.0)  # $200 / $50


@patch("src.live.trader.create_public_exchange")
@patch("src.live.trader.create_hyperliquid_exchange")
@patch("src.live.trader.fetch_available_usdc", return_value=105.0)
def test_calc_order_amount_without_leverage_sizing(_mock_bal, _mock_hl, _mock_pub) -> None:
    config = AppConfig()
    config.exchange = ExchangeConfig(symbol="HYPE/USDC:USDC")
    config.live = LiveConfig(
        position_size_pct=0.95,
        use_leverage_for_sizing=False,
        leverage=5,
        max_notional_usd=200,
        min_notional_usd=50,
    )
    trader = LiveTrader(config, timeframe="1h", dry_run=False)
    trader.exchange = MagicMock()
    trader.exchange.amount_to_precision = lambda _s, a: a

    amount = trader._calc_order_amount(50.0)
    assert amount == pytest.approx(105.0 * 0.95 / 50.0)
