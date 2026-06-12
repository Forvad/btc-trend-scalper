from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OrderType = Literal["maker", "taker"]


@dataclass
class FeeConfig:
    """Комиссии биржи: maker/taker и тип ордера на каждом этапе сделки."""

    maker_pct: float = 0.015
    taker_pct: float = 0.045
    entry: OrderType = "taker"
    exit_stop: OrderType = "taker"
    exit_tp: OrderType = "maker"

    def rate(self, order_type: OrderType) -> float:
        pct = self.maker_pct if order_type == "maker" else self.taker_pct
        return pct / 100

    def entry_rate(self) -> float:
        return self.rate(self.entry)

    def exit_rate(self, exit_reason: str) -> float:
        order_type = self.exit_tp if exit_reason == "take_profit_bb" else self.exit_stop
        return self.rate(order_type)

    def round_trip_pct(self) -> float:
        """Оценка полного цикла: вход + выход (без учёта проскальзывания)."""
        return self.maker_pct + self.taker_pct if self.entry != self.exit_stop else (
            (self.taker_pct if self.entry == "taker" else self.maker_pct)
            + (self.taker_pct if self.exit_stop == "taker" else self.maker_pct)
        )


PRESETS: dict[str, FeeConfig] = {
    "hyperliquid": FeeConfig(
        maker_pct=0.015,
        taker_pct=0.045,
        entry="taker",
        exit_stop="taker",
        exit_tp="maker",
    ),
    "hyperliquid_taker_only": FeeConfig(
        maker_pct=0.015,
        taker_pct=0.045,
        entry="taker",
        exit_stop="taker",
        exit_tp="taker",
    ),
    "binance": FeeConfig(
        maker_pct=0.10,
        taker_pct=0.10,
        entry="taker",
        exit_stop="taker",
        exit_tp="taker",
    ),
}


def get_fee_preset(name: str) -> FeeConfig:
    if name not in PRESETS:
        raise ValueError(f"Unknown fee preset: {name}. Available: {list(PRESETS)}")
    return PRESETS[name]
