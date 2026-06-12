#!/usr/bin/env python3
"""Сравнение последних сделок бэктеста и сигналов стратегии с биржей."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
from dotenv import load_dotenv

from src.backtest import BacktestEngine
from src.backtest.intrabar_align import fetch_intrabar_for_htf, prepare_live_like_data
from src.config import load_config
from src.data import fetch_ohlcv_max
from src.exchange.hyperliquid_client import create_hyperliquid_exchange, has_credentials
from src.strategy import TrendScalperStrategy

load_dotenv()


def main() -> None:
    config = load_config("config.yaml")
    tf = config.default_timeframe
    strategy = TrendScalperStrategy(config.strategy_for_timeframe(tf))

    print(f"\n=== Сигналы и сделки | {config.symbol} | {tf} ===\n")
    df = fetch_ohlcv_max(config.symbol, tf, config.exchange.id)
    data = strategy.generate_signals(df)

    # последние 2 недели
    cutoff = pd.Timestamp("2026-06-01", tz="UTC")
    recent = data[data["timestamp"] >= cutoff].copy()

    print("--- Бары с entry/exit сигналами (с 2026-06-01) ---")
    for _, row in recent.iterrows():
        flags = []
        if row["long_signal"]:
            flags.append("LONG_ENTRY")
        if row["short_signal"]:
            flags.append("SHORT_ENTRY")
        if row["long_exit_tp"]:
            flags.append("LONG_TP")
        if row["long_exit_stop"]:
            flags.append("LONG_SL")
        if row["short_exit_tp"]:
            flags.append("SHORT_TP")
        if row["short_exit_stop"]:
            flags.append("SHORT_SL")
        if not flags:
            continue
        ts = row["timestamp"]
        print(
            f"{ts} | close={row['close']:.3f} | ST={row['supertrend']:.3f} | "
            f"BB=[{row['bb_lower']:.3f}, {row['bb_upper']:.3f}] | "
            f"low={row['low']:.3f} high={row['high']:.3f} | {', '.join(flags)}"
        )

    intrabar_df = None
    if config.backtest.live_like:
        sub_tf = config.backtest.intrabar_timeframe
        intrabar_df = fetch_intrabar_for_htf(
            config.symbol,
            df,
            htf_timeframe=tf,
            sub_timeframe=sub_tf,
            exchange_id=config.exchange.id,
        )
        df, intrabar_df, align = prepare_live_like_data(
            df, intrabar_df, htf_timeframe=tf, sub_timeframe=sub_tf
        )
        print(
            f"Live-like: {align.htf_bars_after} × {tf} + {align.intrabar_bars_after} × {sub_tf} | "
            f"{align.range_start} — {align.range_end}"
        )

    engine = BacktestEngine(
        config.strategy_for_timeframe(tf),
        config.backtest,
        config.exchange.fees,
        live_config=config.live,
    )
    result = engine.run(df, timeframe=tf, intrabar_df=intrabar_df)
    print("\n--- Последние 10 сделок бэктеста ---")
    for t in result.trades[-10:]:
        print(
            f"{t.side.upper():5} entry {t.entry_time} @ {t.entry_price:.3f} -> "
            f"exit {t.exit_time} @ {t.exit_price:.3f} ({t.exit_reason}) "
            f"PnL {t.pnl_pct:+.2f}%"
        )

    if result.open_position_at_end:
        print(
            f"\nОткрытая позиция в конце бэктеста: cash=${result.cash_balance:.2f}, "
            f"equity=${result.final_balance:.2f}"
        )
        last = data.iloc[-1]
        print(
            f"Последняя свеча: {last['timestamp']} close={last['close']:.3f} "
            f"(данные до {df['timestamp'].iloc[-1]})"
        )

    # intrabar: последняя свеча — формирующаяся?
    print("\n--- Последняя свеча (как видит live на каждом тике) ---")
    last = data.iloc[-1]
    print(
        f"{last['timestamp']} | close={last['close']:.3f} | "
        f"long_exit_tp={bool(last['long_exit_tp'])} short_exit_tp={bool(last['short_exit_tp'])} | "
        f"long_signal={bool(last['long_signal'])} short_signal={bool(last['short_signal'])}"
    )

    if has_credentials():
        print("\n--- Последние fills на Hyperliquid ---")
        ex = create_hyperliquid_exchange(require_auth=True)
        since = int(datetime(2026, 6, 7, tzinfo=timezone.utc).timestamp() * 1000)
        try:
            fills = ex.fetch_my_trades(config.symbol, since=since, limit=50)
            for f in fills[-15:]:
                ts = datetime.fromtimestamp(f["timestamp"] / 1000, tz=timezone.utc)
                side = f.get("side", "?")
                price = f.get("price", f.get("average"))
                amount = f.get("amount")
                print(f"{ts} | {side} {amount} @ {price}")
        except Exception as exc:
            print(f"Не удалось загрузить fills: {exc}")
    else:
        print("\n(Нет credentials — fills с биржи не загружены)")


if __name__ == "__main__":
    main()
