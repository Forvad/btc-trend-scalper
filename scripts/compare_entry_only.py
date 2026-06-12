#!/usr/bin/env python3
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tabulate import tabulate

from src.backtest.compare import _run
from src.config import EnhancementConfig, load_config, v2_enhancement_config
from src.data import fetch_ohlcv_max


def main() -> None:
    cfg = load_config()
    rows = []
    for tf in ["15m", "1h", "4h", "1d"]:
        df = fetch_ohlcv_max(cfg.symbol, tf, cfg.exchange.id)
        bcfg = copy.deepcopy(cfg)
        bcfg.strategy.enhancements = EnhancementConfig(enabled=False)
        base = _run(df, None, bcfg, "base")

        v2cfg = copy.deepcopy(cfg)
        v2cfg.strategy.enhancements = v2_enhancement_config()
        v2 = _run(df, None, v2cfg, "v2")

        ecfg = copy.deepcopy(cfg)
        entry_only = v2_enhancement_config()
        entry_only.exit_partial_trail = False
        ecfg.strategy.enhancements = entry_only
        ent = _run(df, None, ecfg, "entry")

        rows.append(
            [
                tf,
                f"{base['return_pct']:+.1f}%",
                f"{ent['return_pct']:+.1f}%",
                f"{v2['return_pct']:+.1f}%",
                base["trades"],
                ent["trades"],
                v2["trades"],
            ]
        )

    print("\n=== Base vs Entry-only vs V2 full ===\n")
    print(
        tabulate(
            rows,
            headers=["TF", "Base", "EntryOnly", "V2 full", "B#", "E#", "V2#"],
            tablefmt="simple",
        )
    )


if __name__ == "__main__":
    main()
