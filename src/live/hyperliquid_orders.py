from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import ccxt

PositionSide = Literal["long", "short"]
BracketTpMode = Literal["dynamic", "tighten", "freeze"]


def reference_price(exchange: ccxt.Exchange, symbol: str) -> float:
    ticker = exchange.fetch_ticker(symbol)
    price = float(ticker.get("last") or ticker.get("close") or 0)
    if price <= 0:
        raise ValueError(f"Не удалось получить цену для {symbol}")
    return float(exchange.price_to_precision(symbol, price))


def round_amount(exchange: ccxt.Exchange, symbol: str, amount: float) -> float:
    precise = float(exchange.amount_to_precision(symbol, amount))
    market = exchange.market(symbol)
    min_amount = float(market.get("limits", {}).get("amount", {}).get("min") or 0)
    if min_amount and precise < min_amount:
        precise = float(exchange.amount_to_precision(symbol, min_amount))
    if precise <= 0:
        raise ValueError(f"Размер ордера после округления = 0 ({amount})")
    return precise


def close_amount(exchange: ccxt.Exchange, symbol: str, position_size: float) -> float:
    """Размер закрытия: не больше реальной позиции (без округления вверх)."""
    if position_size <= 0:
        raise ValueError(f"Пустая позиция: {position_size}")
    precise = float(exchange.amount_to_precision(symbol, position_size))
    if precise > position_size:
        precise = position_size
    if precise <= 0:
        raise ValueError(f"Размер закрытия после округления = 0 ({position_size})")
    return precise


def close_order_side(position_side: PositionSide) -> str:
    return "sell" if position_side == "long" else "buy"


def parse_ccxt_position(
    pos: dict,
    exchange: ccxt.Exchange,
    symbol: str,
) -> tuple[PositionSide, float, float] | None:
    """Парсит позицию ccxt/Hyperliquid: (side, amount, entry_price)."""
    info_pos = pos.get("info", {}).get("position", {})
    szi_raw = info_pos.get("szi")
    if szi_raw is not None:
        szi = float(szi_raw)
        if szi == 0:
            return None
        side: PositionSide = "long" if szi > 0 else "short"
        raw_amount = abs(szi)
    else:
        contracts = float(pos.get("contracts") or 0)
        if contracts == 0:
            return None
        side_str = (pos.get("side") or "").lower()
        if side_str not in ("long", "short"):
            return None
        side = side_str  # type: ignore[assignment]
        raw_amount = contracts

    amount = close_amount(exchange, symbol, raw_amount)
    entry = float(pos.get("entryPrice") or info_pos.get("entryPx") or 0)
    return side, amount, entry


def bracket_levels(side: PositionSide, signal: dict) -> tuple[float, float]:
    """Возвращает (stop_price, take_profit_price)."""
    if side == "long":
        return float(signal["supertrend"]), float(signal["bb_upper"])
    return float(signal["supertrend"]), float(signal["bb_lower"])


def validate_bracket(
    side: PositionSide,
    mark_price: float,
    stop_price: float,
    tp_price: float,
) -> tuple[float | None, float | None]:
    if side == "long":
        stop_ok = stop_price < mark_price
        tp_ok = tp_price > mark_price
    else:
        stop_ok = stop_price > mark_price
        tp_ok = tp_price < mark_price
    return (stop_price if stop_ok else None, tp_price if tp_ok else None)


def sl_distance_pct(side: PositionSide, entry_price: float, stop_price: float) -> float:
    """Расстояние SL от цены входа в % (положительное, если SL на нужной стороне)."""
    if entry_price <= 0:
        return 0.0
    if side == "long":
        return (entry_price - stop_price) / entry_price * 100.0
    return (stop_price - entry_price) / entry_price * 100.0


def is_bracket_sl_valid(
    side: PositionSide,
    signal: dict,
    mark_price: float,
    *,
    min_sl_distance_pct: float = 0.0,
) -> tuple[bool, float, float, float]:
    """
    SL (supertrend) должен быть по правильную сторону от mark
    и не ближе min_sl_distance_pct к цене входа.
    Возвращает (valid, stop_raw, tp_raw, distance_pct).
    """
    stop_raw, tp_raw = bracket_levels(side, signal)
    stop_price, _ = validate_bracket(side, mark_price, stop_raw, tp_raw)
    if stop_price is None:
        return False, stop_raw, tp_raw, 0.0

    distance = sl_distance_pct(side, mark_price, stop_price)
    if min_sl_distance_pct > 0 and distance < min_sl_distance_pct:
        return False, stop_raw, tp_raw, distance

    return True, stop_raw, tp_raw, distance


def bracket_price_key(bracket: dict) -> tuple[float | None, float | None]:
    sl = float(bracket["stopLoss"]["triggerPrice"]) if "stopLoss" in bracket else None
    tp = float(bracket["takeProfit"]["triggerPrice"]) if "takeProfit" in bracket else None
    return sl, tp


def price_tick_size(exchange: ccxt.Exchange, symbol: str) -> float:
    market = exchange.market(symbol)
    precision = market.get("precision", {}).get("price")
    if isinstance(precision, int) and precision >= 0:
        return 10.0 ** (-precision)
    if isinstance(precision, float) and precision > 0:
        return precision
    return 0.0


def resolve_bracket_tp(
    side: PositionSide,
    candidate: float,
    current: float | None,
    mode: BracketTpMode | str,
) -> float:
    """
    Политика TP для bracket-ордеров.

    tighten: long — TP только вниз (ближе), short — только вверх (ближе).
    freeze: TP фиксируется с момента первой постановки.
    """
    if current is None or mode == "dynamic":
        return candidate
    if mode == "freeze":
        return current
    if side == "long":
        return min(current, candidate)
    return max(current, candidate)


def should_update_bracket_leg(
    leg: Literal["sl", "tp"],
    old_price: float | None,
    new_price: float | None,
    *,
    min_tp_change_pct: float = 0.0,
    min_tp_change_ticks: int = 0,
    tick_size: float = 0.0,
) -> bool:
    """Нужно ли обновлять ногу bracket. Для TP — порог % или N тиков (ИЛИ)."""
    if new_price is None:
        return False
    if old_price is None:
        return True
    if old_price == new_price:
        return False
    if leg == "sl":
        return True

    diff = abs(new_price - old_price)
    if min_tp_change_ticks > 0 and tick_size > 0 and diff >= min_tp_change_ticks * tick_size:
        return True
    if min_tp_change_pct > 0 and diff / abs(old_price) * 100 >= min_tp_change_pct:
        return True
    if min_tp_change_pct <= 0 and min_tp_change_ticks <= 0:
        return True
    return False


def bracket_legs_to_update(
    side: PositionSide,
    old_sl: float | None,
    old_tp: float | None,
    new_sl: float | None,
    new_tp: float | None,
    *,
    reason: str,
    min_tp_change_pct: float,
    min_tp_change_ticks: int,
    tick_size: float,
    tp_mode: BracketTpMode | str = "tighten",
) -> tuple[bool, bool]:
    if reason != "update":
        return new_sl is not None, new_tp is not None

    if new_tp is not None:
        new_tp = resolve_bracket_tp(side, new_tp, old_tp, tp_mode)

    update_sl = should_update_bracket_leg("sl", old_sl, new_sl)
    update_tp = should_update_bracket_leg(
        "tp",
        old_tp,
        new_tp,
        min_tp_change_pct=min_tp_change_pct,
        min_tp_change_ticks=min_tp_change_ticks,
        tick_size=tick_size,
    )
    return update_sl, update_tp


def is_stop_loss_order(order: dict) -> bool:
    if order.get("stopLossPrice"):
        return True
    info = order.get("info") or {}
    order_type = str(info.get("orderType") or info.get("order_type") or "").lower()
    if "take profit" in order_type:
        return False
    if "stop" in order_type:
        return True
    return bool(info.get("isTrigger") and order.get("type") == "market")


def is_take_profit_order(order: dict) -> bool:
    if order.get("takeProfitPrice"):
        return True
    info = order.get("info") or {}
    order_type = str(info.get("orderType") or info.get("order_type") or "").lower()
    return "take profit" in order_type


def merge_bracket_prices(
    current: tuple[float | None, float | None] | None,
    placed: dict,
) -> tuple[float | None, float | None]:
    old_sl, old_tp = current or (None, None)
    new_sl, new_tp = bracket_price_key(placed)
    return (
        new_sl if new_sl is not None else old_sl,
        new_tp if new_tp is not None else old_tp,
    )


def should_refresh_bracket(
    ticks_with_position: int,
    every_n_ticks: int,
    *,
    orders_missing: bool,
) -> bool:
    if orders_missing:
        return True
    if every_n_ticks <= 0:
        return False
    return ticks_with_position > 0 and ticks_with_position % every_n_ticks == 0


def build_bracket_params(
    exchange: ccxt.Exchange,
    symbol: str,
    side: PositionSide,
    signal: dict,
    mark_price: float,
) -> dict:
    stop_raw, tp_raw = bracket_levels(side, signal)
    stop_price, tp_price = validate_bracket(side, mark_price, stop_raw, tp_raw)
    params: dict = {}
    if stop_price is not None:
        stop_prec = float(exchange.price_to_precision(symbol, stop_price))
        params["stopLoss"] = {"triggerPrice": stop_prec, "type": "market"}
    if tp_price is not None:
        tp_prec = float(exchange.price_to_precision(symbol, tp_price))
        params["takeProfit"] = {
            "triggerPrice": tp_prec,
            "type": "limit",
            "price": tp_prec,
        }
    return params
