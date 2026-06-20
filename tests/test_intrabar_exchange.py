from src.config import (
    AppConfig,
    BacktestConfig,
    ExchangeConfig,
    hyperliquid_to_usdt_perp,
    load_config,
)


def test_hyperliquid_to_usdt_perp() -> None:
    assert hyperliquid_to_usdt_perp("HYPE/USDC:USDC") == "HYPE/USDT:USDT"
    assert hyperliquid_to_usdt_perp("BTC/USDC:USDC") == "BTC/USDT:USDT"


def test_intrabar_source_defaults_to_main_exchange() -> None:
    cfg = AppConfig(
        exchange=ExchangeConfig(symbol="HYPE/USDC:USDC"),
        backtest=BacktestConfig(),
    )
    assert cfg.intrabar_exchange_id() == "hyperliquid"
    assert cfg.intrabar_symbol() == "HYPE/USDC:USDC"


def test_intrabar_source_binance_mapping() -> None:
    cfg = AppConfig(
        exchange=ExchangeConfig(symbol="HYPE/USDC:USDC"),
        backtest=BacktestConfig(intrabar_exchange="binance"),
    )
    assert cfg.intrabar_exchange_id() == "binance"
    assert cfg.intrabar_symbol() == "HYPE/USDT:USDT"


def test_intrabar_symbol_override() -> None:
    cfg = AppConfig(
        exchange=ExchangeConfig(symbol="HYPE/USDC:USDC"),
        backtest=BacktestConfig(
            intrabar_exchange="binance",
            intrabar_symbol="HYPE/USDT:USDT",
        ),
    )
    assert cfg.intrabar_symbol() == "HYPE/USDT:USDT"


def test_load_config_intrabar_exchange() -> None:
    cfg = load_config("config.yaml")
    assert cfg.backtest.intrabar_exchange == "binance"
    assert cfg.intrabar_symbol() == "HYPE/USDT:USDT"
