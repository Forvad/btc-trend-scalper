#!/usr/bin/env python3
"""BTC Trend Scalper — EMA + Supertrend + Volume."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from tabulate import tabulate

sys.path.insert(0, str(Path(__file__).parent))

from src.backtest import BacktestEngine
from src.config import load_config
from src.backtest.intrabar_align import fetch_intrabar_for_htf, prepare_live_like_data
from src.data import fetch_ohlcv, fetch_ohlcv_max
from src.live import LiveTrader, run_test_orders
from src.notifications import NtfyNotifier
from src.paper import PaperTrader
from src.strategy.htf import htf_for_timeframe
from src.utils.log import app_log, setup_logging
from src.utils.network import is_transient_network_error


def run_backtest(
    timeframe: str,
    config_path: str,
    max_history: bool = False,
    *,
    bot: str = "trend",
) -> None:
    config = load_config(config_path)
    fees = config.exchange.fees
    period_label = "MAX" if max_history else str(config.backtest.candles_limit)
    bot_label = "RANGE (BB+RSI+ADX)" if bot == "range" else "TREND (EMA+ST+Vol)"
    app_log.section(
        f"Backtest: {config.exchange.id} | {config.symbol} | {timeframe} | "
        f"{period_label} | {bot_label}"
    )
    app_log.info(
        f"Комиссии: maker {fees.maker_pct}% / taker {fees.taker_pct}% | "
        f"вход={fees.entry}, стоп={fees.exit_stop}, тейк={fees.exit_tp}"
    )

    app_log.data(f"Загрузка данных с {config.exchange.id}...")
    if max_history:
        df = fetch_ohlcv_max(
            symbol=config.symbol,
            timeframe=timeframe,
            exchange_id=config.exchange.id,
        )
    else:
        df = fetch_ohlcv(
            symbol=config.symbol,
            timeframe=timeframe,
            limit=config.backtest.candles_limit,
            exchange_id=config.exchange.id,
        )

    live_like = bot != "range" and config.backtest.live_like
    strategy = config.strategy_for_timeframe(timeframe)
    intrabar_df = None

    if live_like:
        sub_tf = config.backtest.intrabar_timeframe
        app_log.data(
            f"Загрузка {timeframe} + intrabar ({sub_tf}) для live-like бэктеста..."
        )
        htf_requested_start = df["timestamp"].iloc[0]
        intrabar_df = fetch_intrabar_for_htf(
            config.symbol,
            df,
            htf_timeframe=timeframe,
            sub_timeframe=sub_tf,
            exchange_id=config.exchange.id,
        )
        ib_available_start = intrabar_df["timestamp"].iloc[0]
        if ib_available_start > htf_requested_start:
            gap_days = (ib_available_start - htf_requested_start).days
            app_log.warning(
                f"На бирже {sub_tf} доступен только с {ib_available_start} "
                f"({gap_days} дн. короче запрошенного {timeframe}) — HTF будет обрезан"
            )
        htf_before = len(df)
        df, intrabar_df, align = prepare_live_like_data(
            df,
            intrabar_df,
            htf_timeframe=timeframe,
            sub_timeframe=sub_tf,
        )
        app_log.success(
            f"Live-like: {align.htf_bars_after} × {timeframe} + "
            f"{align.intrabar_bars_after} × {sub_tf} | {align.days} дн. | "
            f"{align.range_start} — {align.range_end}"
        )
        if align.dropped_htf_bars > 0:
            app_log.info(
                f"Обрезано {align.dropped_htf_bars} {timeframe}-баров без полного {sub_tf} "
                f"({htf_before} → {align.htf_bars_after})"
            )
    else:
        days = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days
        app_log.success(
            f"Загружено {len(df)} свечей | {days} дней | "
            f"{df['timestamp'].iloc[0]} — {df['timestamp'].iloc[-1]}"
        )

    htf_df = None
    if strategy.enhancements.needs_htf():
        htf_tf = htf_for_timeframe(timeframe)
        app_log.data(f"Загрузка HTF ({htf_tf})...")
        htf_df = fetch_ohlcv_max(
            symbol=config.symbol,
            timeframe=htf_tf,
            exchange_id=config.exchange.id,
        )

    if bot == "range":
        from src.backtest.range_engine import RangeBacktestEngine

        engine = RangeBacktestEngine(config.range_strategy, config.backtest, config.exchange.fees)
        result = engine.run(df)
    else:
        mode = "ENHANCED" if strategy.enhancements.enabled else "BASELINE"
        sim_mode = "LIVE-LIKE" if config.backtest.live_like else "BAR-CLOSE"
        trail = strategy.trail_sl
        if trail.enabled:
            parts = ["trail SL"]
            if trail.trail_start_at_pct > 0:
                parts.append(f"старт +{trail.trail_start_at_pct:g}%")
            parts.append(f"шаг {trail.trail_step_pct:g}%")
            if trail.breakeven_at_pct > 0:
                parts.append(f"БУ +{trail.breakeven_at_pct:g}%")
            if trail.take_profit_bb:
                parts.append("TP BB")
            trail_label = ", ".join(parts)
        else:
            trail_label = "SL+TP bracket"
        app_log.info(f"Режим: {mode} | симуляция: {sim_mode} | выход: {trail_label}")
        engine = BacktestEngine(
            strategy,
            config.backtest,
            config.exchange.fees,
            live_config=config.live,
        )
        result = engine.run(df, htf_df, timeframe=timeframe, intrabar_df=intrabar_df)

    app_log.section("Результаты")
    app_log.metric("Начальный баланс", f"${result.initial_balance:,.2f}")
    app_log.metric(
        "Конечный баланс",
        f"${result.final_balance:,.2f} (equity, mark-to-market)",
        good=result.final_balance >= result.initial_balance,
    )
    if result.open_position:
        op = result.open_position
        app_log.section("Открытая позиция")
        app_log.metric("Сторона", op.side.upper())
        app_log.metric("Вход", op.entry_time.strftime("%Y-%m-%d %H:%M UTC"))
        app_log.metric("Цена входа", f"${op.entry_price:,.2f}")
        app_log.metric("Размер", f"${op.size_usd:,.2f}")
        app_log.metric("Mark (последняя свеча)", f"${op.mark_price:,.2f}")
        app_log.metric(
            "Нереализ. PnL",
            f"{op.unrealized_pnl_pct:+.2f}% (${op.unrealized_pnl_usd:+,.2f})",
            good=op.unrealized_pnl_usd > 0,
        )
        app_log.metric("Свободный кэш", f"${result.cash_balance:,.2f}")
        open_row = [
            [
                op.side.upper(),
                op.entry_time.strftime("%Y-%m-%d %H:%M"),
                f"{op.entry_price:.2f}",
                "-",
                f"{op.mark_price:.2f} (mark)",
                "OPEN",
                f"{op.unrealized_pnl_pct:+.2f}%",
                f"${op.unrealized_pnl_usd:+.2f}",
            ]
        ]
        app_log.info(
            tabulate(
                open_row,
                headers=["Сторона", "Вход", "Цена входа", "Выход", "Цена", "Статус", "PnL%", "PnL$"],
                tablefmt="simple",
            )
        )
    app_log.metric(
        "Доходность",
        f"{result.total_return_pct:+.2f}%",
        good=result.total_return_pct > 0,
    )
    app_log.metric(
        "Сделок",
        f"{result.total_trades} (long: {result.long_trades}, short: {result.short_trades})",
    )
    app_log.metric("Win Rate", f"{result.win_rate:.1f}%", good=result.win_rate >= 50)
    app_log.metric("Комиссии всего", f"${result.total_fees_usd:,.2f}")
    app_log.metric(
        "Max Drawdown",
        f"{result.max_drawdown_pct:.2f}%",
        good=result.max_drawdown_pct < 20,
    )

    if result.trades:
        table = [
            [
                t.side.upper(),
                t.entry_time.strftime("%Y-%m-%d %H:%M"),
                f"{t.entry_price:.2f}",
                t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "-",
                f"{t.exit_price:.2f}" if t.exit_price else "-",
                t.exit_reason or "-",
                f"{t.pnl_pct:+.2f}%" if t.pnl_pct else "-",
                f"${t.pnl_usd:+.2f}" if t.pnl_usd else "-",
            ]
            for t in result.trades[-20:]
        ]
        app_log.info("\nПоследние сделки (до 20):\n")
        app_log.info(
            tabulate(
                table,
                headers=["Сторона", "Вход", "Цена входа", "Выход", "Цена выхода", "Причина", "PnL%", "PnL$"],
                tablefmt="simple",
            )
        )


def run_paper(timeframe: str, config_path: str) -> None:
    config = load_config(config_path)
    notifier = NtfyNotifier(config.notifications)
    try:
        trader = PaperTrader(config, timeframe=timeframe)
    except Exception as exc:
        notifier.notify_exception(
            mode="PAPER",
            symbol=config.symbol,
            timeframe=timeframe,
            exc=exc,
            context="init",
        )
        raise
    trader.run()


def run_test_orders_cli(config_path: str, *, confirm: bool, side: str) -> None:
    if not confirm:
        app_log.warning(
            "Тестовые ордера на бирже требуют подтверждения.\n"
            "  --confirm-test   открыть и сразу закрыть минимальную позицию\n"
            "  --side long|short|both   по умолчанию long"
        )
        sys.exit(1)

    config = load_config(config_path)
    if config.exchange.id != "hyperliquid":
        app_log.error(f"Тест-ордера поддерживают только hyperliquid, сейчас: {config.exchange.id}")
        sys.exit(1)

    app_log.section(
        f"TEST ORDERS | {config.symbol} | side={side} | "
        f"~${config.live.min_notional_usd:.0f} notional"
    )
    run_test_orders(config, side=side)  # type: ignore[arg-type]


def run_live(timeframe: str, config_path: str, *, confirm: bool, dry_run: bool) -> None:
    if not confirm and not dry_run:
        app_log.warning(
            "LIVE-trading requires confirmation.\n"
            "  --confirm-live   real orders on Hyperliquid\n"
            "  --dry-run        signals only, no orders sent"
        )
        sys.exit(1)

    config = load_config(config_path)
    if config.exchange.id != "hyperliquid":
        app_log.error(f"Live-режим поддерживает только hyperliquid, сейчас: {config.exchange.id}")
        sys.exit(1)

    mode_label = "DRY-RUN" if dry_run else "LIVE (REAL MONEY)"
    app_log.section(f"{mode_label} | {config.symbol} | {timeframe}")

    notifier = NtfyNotifier(config.notifications)
    mode = "DRY-RUN" if dry_run else "LIVE"

    trader: LiveTrader | None = None
    retry_delay_sec = 10.0
    while trader is None:
        try:
            trader = LiveTrader(config, timeframe=timeframe, dry_run=dry_run)
        except Exception as exc:
            if is_transient_network_error(exc):
                app_log.warning(
                    f"Hyperliquid API unavailable at startup ({exc}) — "
                    f"retry in {retry_delay_sec:.0f}s"
                )
                time.sleep(retry_delay_sec)
                retry_delay_sec = min(retry_delay_sec * 1.5, 120.0)
                continue
            notifier.notify_exception(
                mode=mode,
                symbol=config.symbol,
                timeframe=timeframe,
                exc=exc,
                context="init",
            )
            raise

    trader.run()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="BTC Trend Scalper — EMA + Supertrend + Volume",
    )
    parser.add_argument(
        "mode",
        choices=["backtest", "paper", "live", "compare", "compare-bots", "compare-hybrid", "test-orders"],
        help="Режим: backtest, compare-bots, paper, live, test-orders",
    )
    parser.add_argument(
        "--timeframe",
        "-t",
        default=None,
        choices=["15m", "1h", "4h", "1d"],
        help="Таймфрейм (15m, 1h, 4h, 1d); по умолчанию из config default_timeframe",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config.yaml",
        help="Путь к config.yaml",
    )
    parser.add_argument(
        "--max",
        action="store_true",
        help="Загрузить максимум доступной истории с биржи",
    )
    parser.add_argument(
        "--confirm-live",
        action="store_true",
        help="Подтвердить реальную торговлю на Hyperliquid",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Live-логика без отправки ордеров (проверка сигналов)",
    )
    parser.add_argument(
        "--confirm-test",
        action="store_true",
        help="Подтвердить тестовые ордера на Hyperliquid (open + close)",
    )
    parser.add_argument(
        "--side",
        choices=["long", "short", "both"],
        default="long",
        help="Сторона для test-orders (по умолчанию long)",
    )
    parser.add_argument(
        "--bot",
        choices=["trend", "range"],
        default="trend",
        help="Какой бот бэктестить: trend (скальпер) или range (флэт BB+RSI)",
    )
    args = parser.parse_args()
    setup_logging()
    config = load_config(args.config)
    timeframe = args.timeframe or config.default_timeframe

    if args.mode == "backtest":
        run_backtest(timeframe, args.config, max_history=args.max, bot=args.bot)
    elif args.mode == "compare":
        from src.backtest.compare import run_compare
        run_compare(load_config(args.config), max_history=args.max)
    elif args.mode == "compare-bots":
        from src.backtest.compare_bots import run_compare_bots
        run_compare_bots(load_config(args.config), max_history=args.max)
    elif args.mode == "compare-hybrid":
        from src.backtest.compare_hybrid import run_hybrid_compare
        run_hybrid_compare(load_config(args.config), max_history=args.max)
    elif args.mode == "live":
        run_live(timeframe, args.config, confirm=args.confirm_live, dry_run=args.dry_run)
    elif args.mode == "test-orders":
        run_test_orders_cli(args.config, confirm=args.confirm_test, side=args.side)
    else:
        run_paper(timeframe, args.config)


if __name__ == "__main__":
    main()
