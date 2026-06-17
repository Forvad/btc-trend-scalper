#!/usr/bin/env python3
"""Собрать config-{asset}.yaml из tune JSON и шаблона HYPE."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))


# live overrides по символу (bracket TP пороги зависят от цены)
LIVE_OVERRIDES = {
    "HYPE": {
        "bracket_tp_min_change_pct": 0.15,
        "bracket_tp_min_change_ticks": 3,
        "max_notional_usd": 500,
    },
    "BTC": {
        "bracket_tp_min_change_pct": 0.08,
        "bracket_tp_min_change_ticks": 5,
        "max_notional_usd": 2000,
    },
    "ETH": {
        "bracket_tp_min_change_pct": 0.10,
        "bracket_tp_min_change_ticks": 4,
        "max_notional_usd": 1500,
    },
    "SUI": {
        "bracket_tp_min_change_pct": 0.20,
        "bracket_tp_min_change_ticks": 3,
        "max_notional_usd": 500,
    },
    "ZEC": {
        "bracket_tp_min_change_pct": 0.18,
        "bracket_tp_min_change_ticks": 3,
        "max_notional_usd": 500,
    },
}


def asset_from_symbol(symbol: str) -> str:
    return symbol.split("/")[0].upper()


def build_config(template: dict, tune: dict) -> dict:
    cfg = deepcopy(template)
    asset = asset_from_symbol(tune["symbol"])
    cfg["exchange"]["symbol"] = tune["symbol"]

    base_strategy = deepcopy(cfg.get("strategy", {}))
    for key, val in tune["strategy"].items():
        if isinstance(val, dict) and isinstance(base_strategy.get(key), dict):
            base_strategy[key] = {**base_strategy[key], **val}
        else:
            base_strategy[key] = val
    cfg["strategy"] = base_strategy

    sbtf: dict = {}
    for tf, override in (tune.get("strategy_by_timeframe") or {}).items():
        merged = deepcopy(base_strategy)
        for key, val in override.items():
            if isinstance(val, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **val}
            else:
                merged[key] = val
        sbtf[tf] = {k: v for k, v in merged.items() if v != base_strategy.get(k)}
        if not sbtf[tf]:
            sbtf[tf] = override
    cfg["strategy_by_timeframe"] = sbtf

    live = cfg.setdefault("live", {})
    live.update(LIVE_OVERRIDES.get(asset, {}))
    return cfg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", default="configs/config-hype.yaml")
    parser.add_argument("--tune", required=True, help="tune JSON from tune_symbol.py")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    template = yaml.safe_load(Path(args.template).read_text(encoding="utf-8"))
    tune = json.loads(Path(args.tune).read_text(encoding="utf-8"))
    cfg = build_config(template, tune)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        yaml.dump(cfg, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Wrote {out} for {tune['symbol']}")


if __name__ == "__main__":
    main()
