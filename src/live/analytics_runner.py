from __future__ import annotations

from datetime import datetime, timezone

from src.config import AppConfig
from src.exchange.hyperliquid_client import (
    create_hyperliquid_exchange,
    fetch_account_balances,
    has_credentials,
)
from src.live.trade_analytics import analyze_exchange_trades, format_analytics_report


def run_live_trade_analytics(config: AppConfig, *, lookback_days: int | None = None) -> str:
    if not has_credentials():
        raise ValueError("Нужны HYPERLIQUID_PRIVATE_KEY и HYPERLIQUID_WALLET_ADDRESS в .env")

    days = lookback_days if lookback_days is not None else config.live.trade_analytics_days
    exchange = create_hyperliquid_exchange(timeout_sec=config.live.api_timeout_sec)
    _available, equity = fetch_account_balances(exchange)
    stats = analyze_exchange_trades(
        exchange,
        config.symbol,
        equity_usd=equity,
        lookback_days=days,
    )
    return format_analytics_report(stats)


def log_live_trade_analytics(
    config: AppConfig,
    log_fn,
    *,
    dry_run: bool = False,
    lookback_days: int | None = None,
) -> None:
    if dry_run or not config.live.trade_analytics_enabled:
        return
    try:
        report = run_live_trade_analytics(config, lookback_days=lookback_days)
        for line in report.splitlines():
            log_fn(line)
    except Exception as exc:
        log_fn(f"WARN: trade analytics skipped: {exc}")
