#!/usr/bin/env python3
"""Подбор trend-параметров для символа (fast grid + live_like validate)."""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tabulate import tabulate

from src.backtest.engine import BacktestEngine
from src.backtest.intrabar_align import fetch_intrabar_for_backtest, prepare_live_like_data
from src.config import (
    AppConfig,
    BacktestConfig,
    BollingerConfig,
    EnhancementConfig,
    StrategyConfig,
    SupertrendConfig,
    TrailSlConfig,
    load_config,
)
from src.data import fetch_ohlcv_max


TRAIL = TrailSlConfig(
    enabled=True,
    trail_start_at_pct=1.5,
    breakeven_at_pct=0,
    trail_step_pct=0.3,
    take_profit_bb=True,
)


def score(ret: float, dd: float, trades: int, base_trades: int) -> float:
    min_trades = max(int(base_trades * 0.35), 3) if base_trades > 0 else 3
    if trades < min_trades:
        return -9999.0
    return ret - dd * 0.55


def fast_cfg(cfg: AppConfig) -> AppConfig:
    c = copy.deepcopy(cfg)
    c.backtest = copy.deepcopy(cfg.backtest)
    c.backtest.live_like = False
    return c


def live_cfg(cfg: AppConfig) -> AppConfig:
    c = copy.deepcopy(cfg)
    c.backtest = copy.deepcopy(cfg.backtest)
    c.backtest.live_like = True
    return c


def run_bt(
    df,
    strategy: StrategyConfig,
    cfg: AppConfig,
    *,
    timeframe: str,
    intrabar_df=None,
) -> dict:
    r = BacktestEngine(
        strategy,
        cfg.backtest,
        cfg.exchange.fees,
        live_config=cfg.live,
    ).run(df, timeframe=timeframe, intrabar_df=intrabar_df)
    return {
        "ret": r.total_return_pct,
        "trades": r.total_trades,
        "wr": r.win_rate,
        "dd": r.max_drawdown_pct,
        "open": r.open_position_at_end,
    }


def core_grid() -> list[tuple[str, StrategyConfig]]:
    grid: list[tuple[str, StrategyConfig]] = []
    for ema_f, ema_s in ((9, 21), (12, 26), (15, 40), (20, 50), (21, 55)):
        for st_p, st_m in ((7, 2.5), (10, 2.5), (10, 3.0), (10, 3.5), (14, 3.0), (10, 4.0)):
            for bb_p, bb_std in ((20, 2.0), (20, 2.5), (14, 2.0)):
                for vol in (14, 20, 30):
                    s = StrategyConfig(
                        ema_fast=ema_f,
                        ema_slow=ema_s,
                        supertrend=SupertrendConfig(period=st_p, multiplier=st_m),
                        bollinger=BollingerConfig(period=bb_p, std_dev=bb_std),
                        volume_sma_period=vol,
                        enhancements=EnhancementConfig(enabled=False),
                        trail_sl=copy.deepcopy(TRAIL),
                    )
                    tag = f"ema{ema_f}/{ema_s} st{st_p}x{st_m} bb{bb_p}/{bb_std} v{vol}"
                    grid.append((tag, s))
    return grid


def per_tf_variants(base: StrategyConfig) -> list[tuple[str, StrategyConfig]]:
    out: list[tuple[str, StrategyConfig]] = [("base", copy.deepcopy(base))]
    for st_p, st_m in ((7, 2.5), (10, 2.5), (10, 3.0), (10, 3.5), (10, 4.0), (14, 3.0)):
        s = copy.deepcopy(base)
        s.supertrend = SupertrendConfig(period=st_p, multiplier=st_m)
        out.append((f"st{st_p}x{st_m}", s))
    for ema_f, ema_s in ((9, 21), (12, 26), (20, 50)):
        s = copy.deepcopy(base)
        s.ema_fast = ema_f
        s.ema_slow = ema_s
        out.append((f"ema{ema_f}/{ema_s}", s))
    for vol in (14, 20, 30):
        s = copy.deepcopy(base)
        s.volume_sma_period = vol
        out.append((f"v{vol}", s))
    return out


def strategy_to_dict(s: StrategyConfig) -> dict:
    return {
        "ema_fast": s.ema_fast,
        "ema_slow": s.ema_slow,
        "supertrend": {"period": s.supertrend.period, "multiplier": s.supertrend.multiplier},
        "bollinger": {"period": s.bollinger.period, "std_dev": s.bollinger.std_dev},
        "volume_sma_period": s.volume_sma_period,
        "enhancements": {"enabled": False},
    }


def diff_override(best: StrategyConfig, base: StrategyConfig) -> dict:
    override = strategy_to_dict(best)
    base_dict = strategy_to_dict(base)
    return {k: v for k, v in override.items() if v != base_dict.get(k)}


def tune_symbol(cfg: AppConfig, *, primary_tf: str = "1h") -> dict:
    tfs = ["15m", "1h", "4h", "1d"]
    symbol = cfg.symbol
    fast = fast_cfg(cfg)
    live = live_cfg(cfg)

    print(f"\n=== Tuning {symbol} ===\n")
    data = {tf: fetch_ohlcv_max(symbol, tf, cfg.exchange.id) for tf in tfs}

    intrabar: dict[str, object] = {}
    if live.backtest.live_like:
        sub_tf = live.backtest.intrabar_timeframe
        for tf in tfs:
            ib = fetch_intrabar_for_backtest(
                live,
                data[tf],
                htf_timeframe=tf,
            )
            _, intrabar[tf], _ = prepare_live_like_data(
                data[tf], ib, htf_timeframe=tf, sub_timeframe=sub_tf
            )

    base_strategy = StrategyConfig(
        enhancements=EnhancementConfig(enabled=False),
        trail_sl=copy.deepcopy(TRAIL),
    )
    baselines = {}
    for tf in tfs:
        m = run_bt(data[tf], base_strategy, fast, timeframe=tf)
        baselines[tf] = m
        print(f"baseline {tf}: {m['ret']:+.1f}% | {m['trades']} tr | DD {m['dd']:.1f}%")

    grid = core_grid()
    print(f"\nFast core grid on {primary_tf}: {len(grid)} configs...\n")

    ranked: list[dict] = []
    for tag, strategy in grid:
        m = run_bt(data[primary_tf], strategy, fast, timeframe=primary_tf)
        sc = score(m["ret"], m["dd"], m["trades"], baselines[primary_tf]["trades"])
        ranked.append({"tag": tag, "strategy": strategy, "score": sc, "m": m})

    ranked.sort(key=lambda x: x["score"], reverse=True)
    finalists = ranked[:15]

    print(f"Validate top {len(finalists)} on all TF (fast)...\n")
    validated: list[dict] = []
    for row in finalists:
        scores = []
        per_tf = {}
        for tf in tfs:
            m = run_bt(data[tf], row["strategy"], fast, timeframe=tf)
            per_tf[tf] = m
            scores.append(score(m["ret"], m["dd"], m["trades"], baselines[tf]["trades"]))
        validated.append({
            "tag": row["tag"],
            "strategy": row["strategy"],
            "avg_score": sum(scores) / len(scores),
            "per_tf": per_tf,
        })

    validated.sort(key=lambda x: x["avg_score"], reverse=True)
    global_base = copy.deepcopy(validated[0]["strategy"])

    print("=== TOP 5 global (fast) ===")
    print(
        tabulate(
            [
                [i + 1, r["tag"], f"{r['avg_score']:.0f}", f"{r['per_tf']['1h']['ret']:+.0f}%"]
                for i, r in enumerate(validated[:5])
            ],
            headers=["#", "Config", "Score", "1h"],
            tablefmt="simple",
        )
    )

    print("\nPer-TF refine (fast)...\n")
    per_tf_strategies: dict[str, StrategyConfig] = {}
    strategy_by_timeframe: dict[str, dict] = {}
    per_tf_metrics_fast: dict[str, dict] = {}

    for tf in tfs:
        best_name = "base"
        best_s = copy.deepcopy(global_base)
        best_m = run_bt(data[tf], best_s, fast, timeframe=tf)
        best_score = score(best_m["ret"], best_m["dd"], best_m["trades"], baselines[tf]["trades"])

        for name, strategy in per_tf_variants(global_base):
            m = run_bt(data[tf], strategy, fast, timeframe=tf)
            sc = score(m["ret"], m["dd"], m["trades"], baselines[tf]["trades"])
            if sc > best_score:
                best_score = sc
                best_name = name
                best_m = m
                best_s = strategy

        per_tf_strategies[tf] = best_s
        per_tf_metrics_fast[tf] = {"name": best_name, "metrics": best_m}
        override = diff_override(best_s, global_base)
        if override:
            strategy_by_timeframe[tf] = override
        print(
            f"{tf}: {best_name} -> {best_m['ret']:+.1f}% ({best_m['trades']} tr) "
            f"| baseline {baselines[tf]['ret']:+.1f}%"
        )

    print("\nLive-like validation (1h global + per-TF overrides)...\n")
    live_metrics: dict[str, dict] = {}
    m_global = run_bt(
        data["1h"], global_base, live, timeframe="1h", intrabar_df=intrabar.get("1h")
    )
    live_metrics["1h_global"] = m_global
    print(f"1h global: {m_global['ret']:+.1f}% ({m_global['trades']} tr, DD {m_global['dd']:.1f}%)")

    for tf in tfs:
        m = run_bt(
            data[tf],
            per_tf_strategies[tf],
            live,
            timeframe=tf,
            intrabar_df=intrabar.get(tf),
        )
        live_metrics[tf] = m
        print(f"{tf} tuned: {m['ret']:+.1f}% ({m['trades']} tr, DD {m['dd']:.1f}%)")

    return {
        "symbol": symbol,
        "primary_tf": primary_tf,
        "global_tag": validated[0]["tag"],
        "strategy": strategy_to_dict(global_base),
        "strategy_by_timeframe": strategy_by_timeframe,
        "metrics_fast": {tf: per_tf_metrics_fast[tf]["metrics"] for tf in tfs},
        "metrics_live": live_metrics,
        "baselines_fast": baselines,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", default="config.yaml")
    parser.add_argument("--symbol", "-s", required=True, help="e.g. BTC/USDC:USDC")
    parser.add_argument("--out", "-o", help="JSON output path")
    args = parser.parse_args()

    cfg = load_config(args.config)
    cfg.exchange.symbol = args.symbol

    result = tune_symbol(cfg)
    payload = json.dumps(result, indent=2, default=str)
    print("\n=== JSON ===\n")
    print(payload)

    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"\nSaved: {args.out}")


if __name__ == "__main__":
    main()
