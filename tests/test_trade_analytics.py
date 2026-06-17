from datetime import datetime, timezone

import pytest

from src.live.trade_analytics import (
    build_live_trade_analytics,
    calc_apr,
    format_analytics_report,
    parse_closed_trades,
)


def _fill(ts: datetime, direction: str, price: float, amount: float, closed_pnl: float = 0.0) -> dict:
    return {
        "timestamp": int(ts.timestamp() * 1000),
        "price": price,
        "amount": amount,
        "fee": {"cost": 0.1},
        "info": {"dir": direction, "closedPnl": closed_pnl},
    }


def test_parse_long_round_trip() -> None:
    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    fills = [
        _fill(t0, "Open Long", 60.0, 2.0),
        _fill(t1, "Close Long", 62.0, 2.0, closed_pnl=4.0),
    ]
    trades = parse_closed_trades(fills)
    assert len(trades) == 1
    assert trades[0].side == "long"
    assert trades[0].pnl_usd == 4.0
    assert trades[0].pnl_pct == pytest.approx(3.333, rel=1e-3)


def test_parse_short_round_trip() -> None:
    t0 = datetime(2026, 6, 2, 8, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 2, 12, 0, tzinfo=timezone.utc)
    fills = [
        _fill(t0, "Open Short", 70.0, 1.5),
        _fill(t1, "Close Short", 68.0, 1.5, closed_pnl=3.0),
    ]
    trades = parse_closed_trades(fills)
    assert len(trades) == 1
    assert trades[0].side == "short"
    assert trades[0].pnl_pct == pytest.approx(2.857, rel=1e-3)


def test_calc_apr_linear_annualizes_return() -> None:
    # +10% за 30 дней → ~122% годовых (линейно)
    apr = calc_apr(10.0, 30.0)
    assert apr == pytest.approx(121.666, rel=1e-3)


def test_calc_apr_short_period_not_explosive() -> None:
    # +5% за 1 день → 1825% линейно (высоко, но не миллионы)
    apr = calc_apr(5.0, 1.0)
    assert apr == pytest.approx(1825.0, rel=1e-3)
    assert apr < 10_000


def test_estimate_start_capital_floor() -> None:
    from src.live.trade_analytics import _estimate_start_capital

    # нереалистичная оценка старта (<25% equity) → берём текущий equity
    assert _estimate_start_capital(100.0, 95.0) == 100.0
    assert _estimate_start_capital(105.0, 2.0) == pytest.approx(103.0)


def test_build_analytics_win_rate_and_apr() -> None:
    t0 = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 3, 10, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 6, 3, 16, 0, tzinfo=timezone.utc)
    fills = [
        _fill(t0, "Open Long", 60.0, 1.0),
        _fill(t1, "Close Long", 61.0, 1.0, closed_pnl=1.0),
        _fill(t2, "Open Short", 65.0, 1.0),
        _fill(t3, "Close Short", 66.0, 1.0, closed_pnl=-1.0),
    ]
    stats = build_live_trade_analytics(
        symbol="HYPE/USDC:USDC",
        fills=fills,
        equity_usd=105.0,
        period_days=30.0,
    )
    assert stats.trade_count == 2
    assert stats.win_rate == 50.0
    assert stats.total_fees_usd == pytest.approx(0.4)
    assert stats.apr_pct == pytest.approx(stats.return_pct * (365.0 / 30.0), rel=1e-3)
    report = format_analytics_report(stats)
    assert "APR:" in report
