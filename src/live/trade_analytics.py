from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import ccxt

PositionSide = Literal["long", "short"]


@dataclass
class ExchangeClosedTrade:
    side: PositionSide
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    amount: float
    pnl_usd: float
    fees_usd: float

    @property
    def pnl_pct(self) -> float:
        if self.entry_price <= 0:
            return 0.0
        if self.side == "long":
            return (self.exit_price - self.entry_price) / self.entry_price * 100
        return (self.entry_price - self.exit_price) / self.entry_price * 100

    @property
    def net_pnl_usd(self) -> float:
        return self.pnl_usd - self.fees_usd


@dataclass
class LiveTradeAnalytics:
    symbol: str
    period_days: float
    trades: list[ExchangeClosedTrade]
    total_pnl_usd: float
    total_fees_usd: float
    win_rate: float
    capital_usd: float
    return_pct: float
    apr_pct: float

    @property
    def trade_count(self) -> int:
        return len(self.trades)


def _ms_to_dt(ms: int | float | None) -> datetime:
    if ms is None:
        return datetime.now(timezone.utc)
    return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc)


def _fill_fee_usd(fill: dict) -> float:
    fee = fill.get("fee") or {}
    try:
        return float(fee.get("cost") or 0)
    except (TypeError, ValueError):
        return 0.0


def _fill_dir(fill: dict) -> str:
    info = fill.get("info") or {}
    return str(info.get("dir") or "")


def _fill_closed_pnl(fill: dict) -> float:
    info = fill.get("info") or {}
    try:
        return float(info.get("closedPnl") or 0)
    except (TypeError, ValueError):
        return 0.0


def parse_closed_trades(fills: list[dict]) -> list[ExchangeClosedTrade]:
    """Собирает закрытые сделки из Hyperliquid fills (dir Open/Close)."""
    open_long: list[dict] = []
    open_short: list[dict] = []
    closed: list[ExchangeClosedTrade] = []

    for fill in sorted(fills, key=lambda f: f.get("timestamp") or 0):
        direction = _fill_dir(fill)
        amount = float(fill.get("amount") or 0)
        price = float(fill.get("price") or 0)
        ts = _ms_to_dt(fill.get("timestamp"))
        fee = _fill_fee_usd(fill)

        if amount <= 0 or price <= 0:
            continue

        lot = {"time": ts, "price": price, "amount": amount, "fee": fee}

        if direction == "Open Long":
            open_long.append(lot)
            continue
        if direction == "Open Short":
            open_short.append(lot)
            continue
        if direction not in ("Close Long", "Close Short"):
            continue

        if direction == "Close Short":
            pos_side: PositionSide = "short"
            stack = open_short
        else:
            pos_side = "long"
            stack = open_long

        entry = stack.pop(0) if stack else None
        close_fee = fee
        open_fee = float(entry["fee"]) if entry else 0.0
        pnl = _fill_closed_pnl(fill)
        if pnl == 0.0 and entry:
            if pos_side == "long":
                pnl = (price - entry["price"]) * amount
            else:
                pnl = (entry["price"] - price) * amount

        closed.append(
            ExchangeClosedTrade(
                side=pos_side,
                entry_time=entry["time"] if entry else ts,
                exit_time=ts,
                entry_price=float(entry["price"]) if entry else price,
                exit_price=price,
                amount=amount,
                pnl_usd=pnl,
                fees_usd=open_fee + close_fee,
            )
        )

    return closed


def _sum_realized_from_fills(fills: list[dict]) -> tuple[float, float]:
    """Сумма closedPnl только по закрывающим fills + комиссии по всем fills."""
    gross_pnl = 0.0
    total_fees = 0.0
    for fill in fills:
        total_fees += _fill_fee_usd(fill)
        if _fill_dir(fill).startswith("Close"):
            gross_pnl += _fill_closed_pnl(fill)
    return gross_pnl, total_fees


def calc_apr(return_pct: float, period_days: float) -> float:
    """Линейный APR %: доходность за период, приведённая к году без сложного процента."""
    if period_days <= 0:
        return 0.0
    return return_pct * (365.0 / period_days)


def _estimate_start_capital(equity_usd: float, net_pnl: float) -> float:
    """Оценка капитала на начало периода; защита от нереалистично малого знаменателя."""
    estimated = equity_usd - net_pnl
    floor = max(equity_usd * 0.25, 1.0)
    if estimated < floor:
        return max(equity_usd, 1.0)
    return estimated


def build_live_trade_analytics(
    *,
    symbol: str,
    fills: list[dict],
    equity_usd: float,
    period_days: float,
) -> LiveTradeAnalytics:
    trades = parse_closed_trades(fills)
    gross_pnl, total_fees = _sum_realized_from_fills(fills)
    wins = sum(1 for t in trades if t.net_pnl_usd > 0)
    win_rate = (wins / len(trades) * 100.0) if trades else 0.0

    net_pnl = gross_pnl - total_fees
    capital = _estimate_start_capital(equity_usd, net_pnl)
    return_pct = net_pnl / capital * 100.0 if capital > 0 else 0.0

    # APR всегда по окну lookback (мин. 7 дней), не по длительности между сделками
    apr_period_days = max(period_days, 7.0)
    apr_pct = calc_apr(return_pct, apr_period_days)

    return LiveTradeAnalytics(
        symbol=symbol,
        period_days=period_days,
        trades=trades,
        total_pnl_usd=net_pnl,
        total_fees_usd=total_fees,
        win_rate=win_rate,
        capital_usd=capital,
        return_pct=return_pct,
        apr_pct=apr_pct,
    )


def fetch_exchange_fills(
    exchange: ccxt.Exchange,
    symbol: str,
    *,
    since_ms: int | None = None,
    limit: int = 1000,
) -> list[dict]:
    fills = exchange.fetch_my_trades(symbol, since=since_ms, limit=limit)
    return sorted(fills, key=lambda f: f.get("timestamp") or 0)


def analyze_exchange_trades(
    exchange: ccxt.Exchange,
    symbol: str,
    *,
    equity_usd: float,
    lookback_days: int = 30,
) -> LiveTradeAnalytics:
    since_ms = None
    if lookback_days > 0:
        since_ms = int((datetime.now(timezone.utc).timestamp() - lookback_days * 86400) * 1000)
    fills = fetch_exchange_fills(exchange, symbol, since_ms=since_ms)
    return build_live_trade_analytics(
        symbol=symbol,
        fills=fills,
        equity_usd=equity_usd,
        period_days=float(lookback_days),
    )


def format_analytics_report(stats: LiveTradeAnalytics, *, max_trades: int = 15) -> str:
    lines = [
        f"=== Trade analytics | {stats.symbol} | {stats.period_days:.0f}d ===",
        f"Trades: {stats.trade_count} | Win rate: {stats.win_rate:.1f}%",
        f"Net PnL: ${stats.total_pnl_usd:+,.2f} | Fees: ${stats.total_fees_usd:,.2f}",
        f"Return: {stats.return_pct:+.2f}% on ~${stats.capital_usd:,.2f} | "
        f"APR: {stats.apr_pct:+.2f}% (linear, {max(stats.period_days, 7):.0f}d)",
    ]
    if stats.trades:
        lines.append("Last trades:")
        for t in stats.trades[-max_trades:]:
            lines.append(
                f"  {t.side.upper():5} {t.entry_time:%Y-%m-%d %H:%M} {t.entry_price:.2f} -> "
                f"{t.exit_time:%Y-%m-%d %H:%M} {t.exit_price:.2f} | "
                f"net ${t.net_pnl_usd:+.2f} ({t.pnl_pct:+.2f}%)"
            )
    else:
        lines.append("No closed trades in period.")
    return "\n".join(lines)
