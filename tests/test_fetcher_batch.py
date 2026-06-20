from src.data.fetcher import ohlcv_batch_limit


def test_ohlcv_batch_limit_per_exchange() -> None:
    assert ohlcv_batch_limit("hyperliquid") == 5000
    assert ohlcv_batch_limit("binance") == 1000
