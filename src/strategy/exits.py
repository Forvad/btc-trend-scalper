from __future__ import annotations

from typing import Literal

PositionSide = Literal["long", "short"]


def smart_tp_valid(
    side: PositionSide,
    entry_price: float,
    tp_price: float,
    min_profit_pct: float,
) -> bool:
    if side == "long":
        return tp_price >= entry_price * (1 + min_profit_pct / 100)
    return tp_price <= entry_price * (1 - min_profit_pct / 100)
