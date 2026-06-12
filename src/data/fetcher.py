from __future__ import annotations

import time

import ccxt
import pandas as pd

# Hyperliquid отдаёт не более 5000 свечей за запрос
MAX_BATCH_SIZE = 5000


def _to_dataframe(all_candles: list) -> pd.DataFrame:
    df = pd.DataFrame(
        all_candles,
        columns=["timestamp", "open", "high", "low", "close", "volume"],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def fetch_ohlcv(
    symbol: str = "BTC/USDC:USDC",
    timeframe: str = "15m",
    limit: int = 1000,
    exchange_id: str = "hyperliquid",
    exchange: ccxt.Exchange | None = None,
    timeout_sec: int = 30,
) -> pd.DataFrame:
    if exchange is None:
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({"enableRateLimit": True, "timeout": timeout_sec * 1000})

    all_candles: list = []
    since = None
    remaining = limit

    while remaining > 0:
        batch_limit = min(remaining, MAX_BATCH_SIZE)
        candles = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=batch_limit)
        if not candles:
            break

        all_candles.extend(candles)
        since = candles[-1][0] + 1
        remaining -= len(candles)

        if len(candles) < batch_limit:
            break
        time.sleep(exchange.rateLimit / 1000)

    df = _to_dataframe(all_candles)
    return df.tail(limit).reset_index(drop=True)


def fetch_ohlcv_max(
    symbol: str = "BTC/USDC:USDC",
    timeframe: str = "15m",
    exchange_id: str = "hyperliquid",
    start_date: str = "2020-01-01T00:00:00Z",
) -> pd.DataFrame:
    """Загрузить максимум доступной истории с биржи (пагинация вперёд)."""
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})

    since = exchange.parse8601(start_date)
    all_candles: list = []
    seen: set[int] = set()

    while True:
        candles = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=MAX_BATCH_SIZE)
        if not candles:
            break

        for candle in candles:
            ts = candle[0]
            if ts not in seen:
                seen.add(ts)
                all_candles.append(candle)

        since = candles[-1][0] + 1

        if len(candles) < MAX_BATCH_SIZE:
            break
        time.sleep(exchange.rateLimit / 1000)

    return _to_dataframe(all_candles)


def fetch_ohlcv_range(
    symbol: str = "BTC/USDC:USDC",
    timeframe: str = "15m",
    since: pd.Timestamp | str = "2020-01-01T00:00:00Z",
    until: pd.Timestamp | None = None,
    exchange_id: str = "hyperliquid",
    exchange: ccxt.Exchange | None = None,
    timeout_sec: int = 30,
) -> pd.DataFrame:
    """Загрузить свечи в диапазоне [since, until] (until — исключительно для последнего бара)."""
    if exchange is None:
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({"enableRateLimit": True, "timeout": timeout_sec * 1000})

    if isinstance(since, pd.Timestamp):
        since_ms = int(since.timestamp() * 1000)
    else:
        since_ms = exchange.parse8601(since)

    until_ms: int | None = None
    if until is not None:
        until_ms = int(until.timestamp() * 1000)

    all_candles: list = []
    seen: set[int] = set()
    cursor = since_ms

    while True:
        candles = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=MAX_BATCH_SIZE)
        if not candles:
            break

        for candle in candles:
            ts = candle[0]
            if ts < since_ms:
                continue
            if until_ms is not None and ts >= until_ms:
                break
            if ts not in seen:
                seen.add(ts)
                all_candles.append(candle)

        last_ts = candles[-1][0]
        if until_ms is not None and last_ts >= until_ms:
            break
        if last_ts <= cursor:
            break

        cursor = last_ts + 1
        if len(candles) < MAX_BATCH_SIZE:
            break
        time.sleep(exchange.rateLimit / 1000)

    return _to_dataframe(all_candles)
