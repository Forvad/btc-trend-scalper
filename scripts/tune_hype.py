#!/usr/bin/env python3
"""Перебор настроек trend-стратегии для HYPE (max history)."""

from __future__ import annotations

import copy
import itertools
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.config import AppConfig, EnhancementConfig, StrategyConfig, SupertrendConfig, load_config
from src.data import fetch_ohlcv_max


def score(
    ret: float,
    max_dd: float,
    trades: int,
    baseline_trades: int,
    *,
    open_pos: bool,
) -> float:
    """Выше = лучше. Штраф за просадку и слишком мало сделок."""
    if baseline_trades > 0 and trades < baseline_trades * 0.35:
        return -999.0
    trade_factor = min(1.0, trades / max(baseline_trades, 1))
    dd_penalty = max_dd * 0.6
    open_penalty = 5.0 if open_pos else 0.0
    return ret * trade_factor - dd_penalty - open_penalty


def run_one(
    df,
    strategy: StrategyConfig,
    backtest_cfg,
    fees,
) -> dict:
    engine = BacktestEngine(strategy, backtest_cfg, fees)
    r = engine.run(df)
    return {
        "return_pct": r.total_return_pct,
        "trades": r.total_trades,
        "win_rate": r.win_rate,
        "max_dd": r.max_drawdown_pct,
        "final": r.final_balance,
        "open_pos": r.open_position_at_end,
    }


def label_enh(e: EnhancementConfig) -> str:
    if not e.enabled:
        return "baseline"
    parts = []
    if e.entry_filter:
        parts.append(f"pot{e.min_potential_pct:.2f}")
        if e.require_ema_aligned:
            parts.append("ema")
    if e.min_adx > 0:
        parts.append(f"adx{int(e.min_adx)}")
    if e.exit_partial_trail:
        mid = "mid" if e.partial_at_middle else "out"
        be = "be" if e.trail_breakeven_after_partial else "st"
        parts.append(f"pt{e.partial_tp_pct:.0%}-{mid}-{be}")
    if e.trailing_activate_pct > 0 and e.exit_partial_trail:
        parts.append(f"tr{e.trailing_activate_pct:.2f}")
    return "+".join(parts) if parts else "enh-on"


def main() -> None:
    cfg = load_config()
    symbol = cfg.symbol
    exchange = cfg.exchange.id
    tfs = ["15m", "1h", "4h", "1d"]

    print(f"\n=== Tune trend strategy: {symbol} ===\n")
    print("Загрузка данных...")
    data = {tf: fetch_ohlcv_max(symbol, tf, exchange) for tf in tfs}

    baselines: dict[str, dict] = {}
    for tf in tfs:
        s = copy.deepcopy(cfg.strategy)
        s.enhancements = EnhancementConfig(enabled=False)
        baselines[tf] = run_one(data[tf], s, cfg.backtest, cfg.exchange.fees)

    results: list[dict] = []

    # --- Фаза 1: фильтр входа ---
    entry_grid = []
    for pot in (0.0, 0.05, 0.08, 0.10, 0.13, 0.15, 0.20, 0.25):
        for ema in (False, True):
            entry_grid.append(
                EnhancementConfig(
                    enabled=pot > 0 or ema,
                    entry_filter=pot > 0,
                    min_potential_pct=pot if pot > 0 else 0.10,
                    require_ema_aligned=ema,
                    exit_partial_trail=False,
                )
            )
    # --- Фаза 2: выход partial+trail (лучшие entry из фазы 1 добавим после) ---
    exit_grid = []
    for partial_pct in (0.25, 0.35, 0.50):
        for at_middle in (True, False):
            for trail_be in (True, False):
                for trail_act in (0.15, 0.20, 0.30):
                    exit_grid.append(
                        EnhancementConfig(
                            enabled=True,
                            entry_filter=True,
                            min_potential_pct=0.10,
                            require_ema_aligned=False,
                            exit_partial_trail=True,
                            partial_tp_pct=partial_pct,
                            partial_at_middle=at_middle,
                            trail_breakeven_after_partial=trail_be,
                            trailing_activate_pct=trail_act,
                        )
                    )

    # --- Фаза 3: supertrend + лучший entry pot ---
    st_grid = []
    for mult in (2.5, 3.0, 3.5, 4.0):
        for pot in (0.08, 0.10, 0.13):
            st_grid.append((mult, pot))

    def eval_config(
        strategy: StrategyConfig,
        tag: str,
        phase: str,
    ) -> None:
        per_tf: dict[str, dict] = {}
        scores = []
        rets = []
        for tf in tfs:
            m = run_one(data[tf], copy.deepcopy(strategy), cfg.backtest, cfg.exchange.fees)
            per_tf[tf] = m
            sc = score(
                m["return_pct"],
                m["max_dd"],
                m["trades"],
                baselines[tf]["trades"],
                open_pos=m["open_pos"],
            )
            scores.append(sc)
            rets.append(m["return_pct"])

        avg_score = sum(scores) / len(scores)
        min_ret = min(rets)
        results.append({
            "phase": phase,
            "tag": tag,
            "avg_score": avg_score,
            "min_ret": min_ret,
            "total_ret": sum(rets),
            "15m": rets[0],
            "1h": rets[1],
            "4h": rets[2],
            "1d": rets[3],
            "trades": sum(per_tf[tf]["trades"] for tf in tfs),
            "strategy": copy.deepcopy(strategy),
            "per_tf": per_tf,
        })

    print("Фаза 1: фильтр входа + baseline...")
    s0 = copy.deepcopy(cfg.strategy)
    s0.enhancements = EnhancementConfig(enabled=False)
    eval_config(s0, "baseline", "entry")

    for enh in entry_grid:
        s = copy.deepcopy(cfg.strategy)
        s.enhancements = enh
        eval_config(s, label_enh(enh), "entry")

    print("Фаза 2: partial + trail...")
    for enh in exit_grid:
        s = copy.deepcopy(cfg.strategy)
        s.enhancements = enh
        eval_config(s, label_enh(enh), "exit")

    print("Фаза 3: supertrend multiplier...")
    for mult, pot in st_grid:
        s = copy.deepcopy(cfg.strategy)
        s.supertrend = SupertrendConfig(period=10, multiplier=mult)
        s.enhancements = EnhancementConfig(
            enabled=True,
            entry_filter=True,
            min_potential_pct=pot,
            require_ema_aligned=False,
            exit_partial_trail=False,
        )
        eval_config(s, f"st{mult}+pot{pot:.2f}", "supertrend")

    # --- Фаза 4: тонкая настройка вокруг лидеров entry ---
    top_entry = sorted(
        [r for r in results if r["phase"] == "entry"],
        key=lambda x: x["avg_score"],
        reverse=True,
    )[:5]
    print("Фаза 4: уточнение лучших entry...")
    for leader in top_entry:
        base_pot = leader["strategy"].enhancements.min_potential_pct
        for pot in (base_pot - 0.02, base_pot, base_pot + 0.02):
            if pot < 0:
                continue
            for min_adx in (0, 15, 18):
                s = copy.deepcopy(leader["strategy"])
                s.enhancements.min_potential_pct = pot
                s.enhancements.min_adx = float(min_adx)
                if min_adx == 0:
                    s.enhancements.enabled = s.enhancements.entry_filter or pot > 0
                else:
                    s.enhancements.enabled = True
                eval_config(
                    s,
                    f"fine-pot{pot:.2f}+adx{min_adx}",
                    "fine",
                )

    results.sort(key=lambda x: x["avg_score"], reverse=True)

    print("\n=== TOP 15 (avg score по всем TF) ===\n")
    top = results[:15]
    table = [
        [
            i + 1,
            r["phase"],
            r["tag"],
            f"{r['avg_score']:.1f}",
            f"{r['15m']:+.0f}%",
            f"{r['1h']:+.0f}%",
            f"{r['4h']:+.0f}%",
            f"{r['1d']:+.0f}%",
            r["trades"],
            f"{r['min_ret']:+.0f}%",
        ]
        for i, r in enumerate(top)
    ]
    print(
        tabulate(
            table,
            headers=["#", "Phase", "Config", "Score", "15m", "1h", "4h", "1d", "Trades", "MinTF"],
            tablefmt="simple",
        )
    )

    best = results[0]
    print(f"\n=== Лучший общий конфиг: {best['tag']} (score {best['avg_score']:.1f}) ===\n")
    enh = best["strategy"].enhancements
    st = best["strategy"].supertrend
    print(f"supertrend: period={st.period} multiplier={st.multiplier}")
    print("enhancements:")
    for k, v in asdict(enh).items():
        print(f"  {k}: {v}")

    # Лучший per-TF
    print("\n=== Лучший конфиг PER TF ===\n")
    per_tf_rows = []
    for tf_idx, tf in enumerate(tfs):
        tf_results = []
        for r in results:
            m = r["per_tf"][tf]
            sc = score(
                m["return_pct"],
                m["max_dd"],
                m["trades"],
                baselines[tf]["trades"],
                open_pos=m["open_pos"],
            )
            tf_results.append((sc, r))
        tf_results.sort(key=lambda x: x[0], reverse=True)
        br = tf_results[0][1]
        bm = br["per_tf"][tf]
        base = baselines[tf]
        per_tf_rows.append([
            tf,
            f"{base['return_pct']:+.0f}%",
            f"{bm['return_pct']:+.0f}%",
            br["tag"],
            bm["trades"],
            f"{bm['max_dd']:.1f}%",
        ])
    print(
        tabulate(
            per_tf_rows,
            headers=["TF", "Baseline", "Best", "Config", "Trades", "DD"],
            tablefmt="simple",
        )
    )

    # Baseline reference
    print("\n=== Baseline reference ===\n")
    for tf in tfs:
        b = baselines[tf]
        print(f"  {tf}: {b['return_pct']:+.1f}% | {b['trades']} trades | DD {b['max_dd']:.1f}%")


if __name__ == "__main__":
    main()
