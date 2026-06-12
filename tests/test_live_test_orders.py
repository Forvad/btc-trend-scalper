from unittest.mock import MagicMock, patch

import pytest

from src.config import AppConfig, ExchangeConfig, LiveConfig
from src.live.test_orders import LiveOrderTester


@pytest.fixture
def config() -> AppConfig:
    cfg = AppConfig()
    cfg.exchange = ExchangeConfig(symbol="HYPE/USDC:USDC")
    cfg.live = LiveConfig(min_notional_usd=50, slippage=0.005, leverage=5)
    return cfg


@patch("src.live.test_orders.has_credentials", return_value=True)
@patch("src.live.test_orders.create_hyperliquid_exchange")
def test_roundtrip_long(mock_create_ex, _mock_creds, config: AppConfig) -> None:
    exchange = MagicMock()
    mock_create_ex.return_value = exchange
    exchange.fetch_ticker.return_value = {"last": 40.0}
    exchange.amount_to_precision = lambda _s, amount: round(amount, 2)
    exchange.price_to_precision = lambda _s, price: price
    exchange.market.return_value = {"limits": {"amount": {"min": 1.0}}}
    exchange.create_order.side_effect = [
        {"id": "entry-1"},
        {"id": "exit-1"},
    ]
    exchange.fetch_positions.side_effect = [
        [{"contracts": 1.25, "side": "long", "entryPrice": 40.0}],
        [],
    ]

    tester = LiveOrderTester(config)
    result = tester._roundtrip("long")

    assert result.side == "long"
    assert result.entry_order["id"] == "entry-1"
    assert exchange.create_order.call_count == 2
    buy_call = exchange.create_order.call_args_list[0]
    assert buy_call.args[2] == "buy"
    sell_call = exchange.create_order.call_args_list[1]
    assert sell_call.args[2] == "sell"
    assert sell_call.kwargs["params"]["reduceOnly"] is True
