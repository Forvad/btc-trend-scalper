from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from src.strategy.exits import smart_tp_valid
from src.live.analytics_runner import log_live_trade_analytics
from src.config import AppConfig
from src.live.hyperliquid_orders import (
    bracket_legs_to_update,
    bracket_levels,
    bracket_price_key,
    build_bracket_params,
    close_amount,
    close_order_side,
    is_stop_loss_order,
    is_take_profit_order,
    merge_bracket_prices,
    parse_ccxt_position,
    price_tick_size,
    reference_price,
    round_amount,
    should_refresh_bracket,
    is_bracket_sl_valid,
    validate_bracket,
)
from src.data import fetch_ohlcv
from src.exchange.hyperliquid_client import (
    create_hyperliquid_exchange,
    create_public_exchange,
    diagnose_wallet_setup,
    fetch_account_balances,
    fetch_available_usdc,
    has_credentials,
)
from src.notifications import NtfyNotifier
from src.strategy import TrendScalperStrategy
from src.strategy.htf import htf_for_timeframe
from src.utils.log import Log, setup_logging
from src.utils.runtime import call_with_timeout

PositionSide = Literal["long", "short"]


@dataclass
class LivePosition:
    side: PositionSide
    amount: float
    entry_price: float


class LiveTrader:
    def __init__(self, config: AppConfig, timeframe: str = "15m", dry_run: bool = False) -> None:
        self.config = config
        self.timeframe = timeframe
        self.dry_run = dry_run
        self.symbol = config.symbol
        self.strategy = TrendScalperStrategy(config.strategy_for_timeframe(timeframe))
        self.fees = config.exchange.fees
        self.live = config.live
        self.notifier = NtfyNotifier(config.notifications)
        self._last_heartbeat = time.monotonic()
        self._last_trade_analytics = 0.0
        self._position_tick_count = 0
        self._last_bracket_prices: tuple[float | None, float | None] | None = None
        auth_required = not dry_run or has_credentials()
        self.exchange = create_hyperliquid_exchange(
            require_auth=auth_required,
            timeout_sec=self.live.api_timeout_sec,
        )
        self._public_exchange = create_public_exchange(
            config.exchange.id,
            timeout_sec=self.live.api_timeout_sec,
        )
        self.log = Log("DRY-RUN" if dry_run else "LIVE")
        self._setup_leverage()

    def _log(self, message: str) -> None:
        self.log.smart(message)

    def _reconnect_exchange(self) -> None:
        self._log("Reconnecting exchange after timeout...")
        auth_required = not self.dry_run or has_credentials()
        self.exchange = create_hyperliquid_exchange(
            require_auth=auth_required,
            timeout_sec=self.live.api_timeout_sec,
        )
        self._public_exchange = create_public_exchange(
            self.config.exchange.id,
            timeout_sec=self.live.api_timeout_sec,
        )
        if not self.dry_run:
            self._setup_leverage()

    def _maybe_heartbeat(self) -> None:
        now = time.monotonic()
        if now - self._last_heartbeat < self.live.heartbeat_interval_sec:
            return
        self._last_heartbeat = now
        self._log("HEARTBEAT — bot is running")
        self._maybe_trade_analytics()

    def _maybe_trade_analytics(self, *, force: bool = False) -> None:
        interval = self.live.trade_analytics_interval_sec
        if not force:
            if interval <= 0:
                return
            if time.monotonic() - self._last_trade_analytics < interval:
                return
        self._last_trade_analytics = time.monotonic()
        log_live_trade_analytics(self.config, self._log, dry_run=self.dry_run)

    @property
    def _mode_label(self) -> str:
        return "DRY-RUN" if self.dry_run else "LIVE"

    def _report_error(self, exc: BaseException, *, context: str | None = None) -> None:
        self._log(f"ERROR: {exc}")
        self.notifier.notify_exception(
            mode=self._mode_label,
            symbol=self.symbol,
            timeframe=self.timeframe,
            exc=exc,
            context=context,
        )

    def _handle_tick_failure(self, exc: BaseException, *, context: str) -> None:
        if is_transient_network_error(exc) or isinstance(exc, TimeoutError):
            self._log(f"WARN: {context}: {exc} — retry next tick")
            self._reconnect_exchange()
            return
        self._report_error(exc, context=context)

    def _get_balances(self) -> tuple[float, float]:
        if self.dry_run and not has_credentials():
            return 10_000.0, 10_000.0
        return fetch_account_balances(self.exchange)

    def _setup_leverage(self) -> None:
        if self.dry_run:
            return
        self.exchange.set_leverage(
            self.live.leverage,
            self.symbol,
            params={"marginMode": self.live.margin_mode},
        )
        self._log(f"Leverage set: {self.live.leverage}x ({self.live.margin_mode})")

    def _fetch_htf(self):
        if not self.strategy.config.enhancements.needs_htf():
            return None
        return fetch_ohlcv(
            symbol=self.symbol,
            timeframe=htf_for_timeframe(self.timeframe),
            limit=self.config.backtest.candles_limit,
            exchange=self._public_exchange,
        )

    def _get_exchange_position(self) -> LivePosition | None:
        if self.dry_run and not has_credentials():
            return None
        positions = self.exchange.fetch_positions([self.symbol])
        for pos in positions:
            parsed = parse_ccxt_position(pos, self.exchange, self.symbol)
            if parsed is None:
                continue
            side, amount, entry = parsed
            return LivePosition(side, amount, entry)
        return None

    def _reference_price(self) -> float:
        if self.dry_run and not has_credentials():
            return 0.0
        return reference_price(self.exchange, self.symbol)

    def _cancel_open_orders(self, *, pause_sec: float = 1.0) -> None:
        if self.dry_run:
            return
        for order in self.exchange.fetch_open_orders(self.symbol):
            self.exchange.cancel_order(order["id"], self.symbol)
            self._log(f"Canceled order {order.get('id')} ({order.get('type')})")
        if pause_sec > 0:
            time.sleep(pause_sec)

    def _cancel_bracket_orders(
        self,
        *,
        cancel_sl: bool,
        cancel_tp: bool,
        pause_sec: float = 0.5,
    ) -> None:
        if self.dry_run or (not cancel_sl and not cancel_tp):
            return
        for order in self.exchange.fetch_open_orders(self.symbol):
            cancel = (cancel_sl and is_stop_loss_order(order)) or (
                cancel_tp and is_take_profit_order(order)
            )
            if not cancel:
                continue
            self.exchange.cancel_order(order["id"], self.symbol)
            leg = "SL" if is_stop_loss_order(order) else "TP"
            self._log(f"Canceled {leg} order {order.get('id')} ({order.get('type')})")
        if pause_sec > 0:
            time.sleep(pause_sec)

    def _has_trigger_orders(self) -> bool:
        if self.dry_run:
            return False
        for order in self.exchange.fetch_open_orders(self.symbol):
            info = order.get("info") or {}
            if info.get("triggerPx") or info.get("isTrigger") or order.get("triggerPrice"):
                return True
            if order.get("stopLossPrice") or order.get("takeProfitPrice"):
                return True
        return False

    def _calc_order_amount(self, price: float) -> float:
        if self.dry_run and not has_credentials():
            available = 10_000.0
        else:
            available = fetch_available_usdc(self.exchange)

        leverage = self.live.leverage if self.live.use_leverage_for_sizing else 1
        buying_power = available * max(leverage, 1)
        notional = buying_power * self.live.position_size_pct
        notional = min(notional, self.live.max_notional_usd)

        min_margin = (
            self.live.min_notional_usd / max(self.live.leverage, 1)
            if self.live.use_leverage_for_sizing
            else self.live.min_notional_usd
        )
        if available < min_margin:
            raise ValueError(
                f"Notional ${notional:.2f} < min ${self.live.min_notional_usd:.2f} "
                f"(balance ${available:.2f}, need margin ${min_margin:.2f})"
            )

        if notional < self.live.min_notional_usd:
            if buying_power >= self.live.min_notional_usd:
                notional = self.live.min_notional_usd
            else:
                raise ValueError(
                    f"Notional ${notional:.2f} < min ${self.live.min_notional_usd:.2f} "
                    f"(balance ${available:.2f}, buying power ${buying_power:.2f})"
                )

        if self.live.use_leverage_for_sizing:
            notional = min(notional, buying_power)
        else:
            notional = min(notional, available)

        amount = notional / price
        return float(self.exchange.amount_to_precision(self.symbol, amount))

    def _place_market(
        self,
        order_side: str,
        amount: float,
        *,
        reduce_only: bool = False,
        label: str = "",
        bracket: dict | None = None,
    ) -> dict | None:
        amount = round_amount(self.exchange, self.symbol, amount)
        ref_price = self._reference_price()
        params: dict = {"slippage": str(self.live.slippage)}
        if reduce_only:
            params["reduceOnly"] = True
        if bracket:
            params.update(bracket)

        self._log(
            f"ORDER {label}: {order_side.upper()} market {amount} {self.symbol} "
            f"@ ref {ref_price} (slippage {self.live.slippage * 100:.2f}%)"
            + (f" | bracket SL/TP" if bracket else "")
        )

        if self.dry_run:
            return {"id": "dry-run", "status": "dry_run"}

        return self.exchange.create_order(
            self.symbol,
            "market",
            order_side,
            amount,
            ref_price,
            params=params,
        )

    def _place_market_reduce(
        self,
        position_side: PositionSide,
        amount: float,
        *,
        label: str,
    ) -> dict | None:
        order_side = close_order_side(position_side)
        amount = close_amount(self.exchange, self.symbol, amount)
        ref_price = self._reference_price()
        self._log(
            f"ORDER {label}: {order_side.upper()} market {amount} {self.symbol} "
            f"@ ref {ref_price} (reduceOnly, slippage {self.live.slippage * 100:.2f}%)"
        )
        if self.dry_run:
            return {"id": "dry-run", "status": "dry_run"}

        try:
            return self.exchange.create_order(
                self.symbol,
                "market",
                order_side,
                amount,
                ref_price,
                params={"slippage": str(self.live.slippage), "reduceOnly": True},
            )
        except Exception as exc:
            err = str(exc).lower()
            if "reduce only" in err or "increase position" in err:
                self._log(f"{label} failed ({exc}) — перепроверяю позицию...")
                if self._get_exchange_position() is None:
                    self._log(f"{label} skipped — позиция уже закрыта")
                    return None
            raise

    def _place_bracket_only(self, pos: LivePosition, bracket: dict) -> None:
        """SL/TP для уже открытой позиции (без нового входа)."""
        if self.dry_run:
            self._log(f"DRY-RUN bracket: {bracket}")
            self._last_bracket_prices = merge_bracket_prices(self._last_bracket_prices, bracket)
            return

        close_side = close_order_side(pos.side)
        amount = close_amount(self.exchange, self.symbol, pos.amount)

        if "stopLoss" in bracket:
            sl = float(bracket["stopLoss"]["triggerPrice"])
            self._log(f"ORDER SL trigger: {close_side.upper()} @ {sl}")
            self.exchange.create_order(
                self.symbol,
                "market",
                close_side,
                amount,
                sl,
                params={"stopLossPrice": sl, "reduceOnly": True},
            )

        if "takeProfit" in bracket:
            tp = float(bracket["takeProfit"]["triggerPrice"])
            self._log(f"ORDER TP limit: {close_side.upper()} @ {tp}")
            self.exchange.create_order(
                self.symbol,
                "limit",
                close_side,
                amount,
                tp,
                params={"takeProfitPrice": tp, "reduceOnly": True, "postOnly": True},
            )

        self._last_bracket_prices = merge_bracket_prices(self._last_bracket_prices, bracket)

    def _sync_bracket_orders(self, pos: LivePosition, signal: dict, *, reason: str) -> None:
        if not self.live.place_bracket_orders:
            return

        mark = float(signal["close"])
        if not self.dry_run:
            mark = self._reference_price()

        bracket = build_bracket_params(self.exchange, self.symbol, pos.side, signal, mark)
        if not bracket:
            self._log(f"Bracket {reason}: пропуск — невалидные уровни SL/TP")
            return

        new_sl, new_tp = bracket_price_key(bracket)
        old_sl, old_tp = self._last_bracket_prices or (None, None)
        tick_size = price_tick_size(self.exchange, self.symbol) if not self.dry_run else 0.01

        update_sl, update_tp = bracket_legs_to_update(
            pos.side,
            old_sl,
            old_tp,
            new_sl,
            new_tp,
            reason=reason,
            min_tp_change_pct=self.live.bracket_tp_min_change_pct,
            min_tp_change_ticks=self.live.bracket_tp_min_change_ticks,
            tick_size=tick_size,
            tp_mode=self.live.bracket_tp_mode,
        )

        if reason == "update" and not update_sl and not update_tp:
            self._log(
                f"Bracket update: пропуск — SL={old_sl} TP={old_tp} "
                f"(кандидаты {new_sl}/{new_tp}, режим TP={self.live.bracket_tp_mode}, "
                f"порог {self.live.bracket_tp_min_change_pct}%)"
            )
            return

        stop_raw, tp_raw = bracket_levels(pos.side, signal)
        legs = []
        if update_sl:
            legs.append(f"SL={new_sl}")
        if update_tp:
            legs.append(f"TP={new_tp}")
        self._log(
            f"Bracket {reason}: обновление {', '.join(legs) or 'нет'} "
            f"(кандидаты SL={new_sl} TP={new_tp}, supertrend={stop_raw:.4f}, bb={tp_raw:.4f}, mark={mark:.4f})"
        )

        if not self.dry_run:
            self._cancel_bracket_orders(cancel_sl=update_sl, cancel_tp=update_tp, pause_sec=0.5)
            fresh = self._get_exchange_position()
            if fresh is None:
                self._log(f"Bracket {reason} canceled — позиция уже закрыта")
                return
            pos = fresh

        partial: dict = {}
        if update_sl and "stopLoss" in bracket:
            partial["stopLoss"] = bracket["stopLoss"]
        if update_tp and "takeProfit" in bracket:
            partial["takeProfit"] = bracket["takeProfit"]
        if not partial:
            return

        self._place_bracket_only(pos, partial)

    def _manage_bracket_orders(self, pos: LivePosition, signal: dict) -> str | None:
        if not self.live.place_bracket_orders:
            return None

        self._position_tick_count += 1

        if not self.dry_run and not self._has_trigger_orders():
            self._sync_bracket_orders(pos, signal, reason="restore")
            return "bracket_restore"

        if not self.live.update_bracket_orders:
            return None

        if should_refresh_bracket(
            self._position_tick_count,
            self.live.bracket_update_every_ticks,
            orders_missing=False,
        ):
            self._sync_bracket_orders(pos, signal, reason="update")
            return "bracket_update"

        return None

    def _place_limit_tp(
        self,
        side: PositionSide,
        amount: float,
        price: float,
    ) -> dict | None:
        order_side = "sell" if side == "long" else "buy"
        price_prec = float(self.exchange.price_to_precision(self.symbol, price))
        self._log(f"ORDER TP: {order_side.upper()} limit {amount} @ {price_prec}")

        if self.dry_run:
            return {"id": "dry-run-tp", "status": "dry_run"}

        return self.exchange.create_order(
            self.symbol,
            "limit",
            order_side,
            amount,
            price_prec,
            params={"reduceOnly": True, "postOnly": True},
        )

    def _open_position(self, side: PositionSide, signal: dict) -> bool:
        price = signal["close"]
        amount = self._calc_order_amount(price)
        order_side = "buy" if side == "long" else "sell"
        label = "OPEN LONG" if side == "long" else "OPEN SHORT"

        bracket = None
        if self.live.place_bracket_orders:
            mark = price if self.dry_run and not has_credentials() else self._reference_price()
            sl_valid, stop_raw, tp_raw, sl_dist = is_bracket_sl_valid(
                side,
                signal,
                mark,
                min_sl_distance_pct=self.live.min_sl_distance_pct,
            )
            if signal.get("overheated") and side == "long":
                self._log(
                    f"SKIP {label}: перегрев — рост {signal.get('momentum_rise_pct', 0):.1f}% "
                    f"за {self.strategy.config.momentum_filter.lookback_bars} бар(ов)"
                )
                return False
            if not sl_valid:
                need = "выше" if side == "short" else "ниже"
                stop_price, _ = validate_bracket(side, mark, stop_raw, tp_raw)
                if stop_price is None:
                    self._log(
                        f"SKIP {label}: SL невалиден — supertrend={stop_raw:.4f} "
                        f"должен быть {need} mark={mark:.4f} (tp_band={tp_raw:.4f})"
                    )
                else:
                    self._log(
                        f"SKIP {label}: SL слишком близко — dist={sl_dist:.2f}% "
                        f"< min {self.live.min_sl_distance_pct:.2f}% "
                        f"(supertrend={stop_raw:.4f}, mark={mark:.4f})"
                    )
                return False
            bracket = build_bracket_params(self.exchange, self.symbol, side, signal, mark)
            stop_ok, tp_ok = validate_bracket(side, mark, stop_raw, tp_raw)
            self._log(
                f"Bracket plan: SL={stop_ok} TP={tp_ok} "
                f"(supertrend={stop_raw:.4f}, tp_band={tp_raw:.4f}, mark={mark:.4f})"
            )

        order = self._place_market(order_side, amount, label=label, bracket=bracket)
        if not self.dry_run:
            time.sleep(2)
            placed = self._get_exchange_position()
            if placed:
                amount = placed.amount
        self._position_tick_count = 0
        if bracket:
            self._last_bracket_prices = bracket_price_key(bracket)
        self._log(f"{label} filled | amount={amount} | price~{price:.2f} | order={order}")
        notional = amount * price
        free, equity = self._get_balances()
        self.notifier.notify_trade_open(
            mode="LIVE" if not self.dry_run else "DRY-RUN",
            side=side,
            symbol=self.symbol,
            timeframe=self.timeframe,
            price=price,
            size_usd=notional,
            amount=amount,
            balance_usd=free,
            equity_usd=equity,
        )
        return True

    def _close_position(
        self,
        pos: LivePosition,
        signal: dict,
        exit_price: float,
        exit_reason: str,
    ) -> None:
        enh = self.strategy.config.enhancements
        use_limit = (
            exit_reason == "take_profit_bb"
            and self.fees.exit_tp == "maker"
            and not self.dry_run
            and enh.enabled
            and enh.smart_tp
        )

        if use_limit:
            if not smart_tp_valid(pos.side, pos.entry_price, exit_price, enh.min_potential_pct):
                use_limit = False

        label = f"CLOSE {pos.side.upper()} ({exit_reason})"
        self._cancel_open_orders()

        fresh = self._get_exchange_position()
        if fresh is None:
            self._log(f"{label} skipped — позиция уже закрыта на бирже")
            return

        order_side = close_order_side(fresh.side)
        if order_side != close_order_side(pos.side):
            self._log(
                f"{label} aborted — сторона позиции изменилась "
                f"({pos.side} -> {fresh.side})"
            )
            return

        size = close_amount(self.exchange, self.symbol, fresh.amount)

        if use_limit:
            order = self._place_limit_tp(fresh.side, size, exit_price)
        else:
            order = self._place_market_reduce(fresh.side, size, label=label)
        pos = fresh

        self._log(f"{label} | amount={size} | target={exit_price:.2f} | order={order}")

        if pos.side == "long":
            pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100
        else:
            pnl_pct = (pos.entry_price - exit_price) / pos.entry_price * 100
        pnl_usd = pos.amount * pos.entry_price * pnl_pct / 100

        free, equity = self._get_balances()
        self.notifier.notify_trade_close(
            mode="LIVE" if not self.dry_run else "DRY-RUN",
            side=pos.side,
            symbol=self.symbol,
            timeframe=self.timeframe,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            reason=exit_reason,
            pnl_usd=pnl_usd,
            pnl_pct=pnl_pct,
            balance_usd=free,
            equity_usd=equity,
        )
        self._position_tick_count = 0
        self._last_bracket_prices = None

    def _resolve_exit(
        self,
        pos: LivePosition,
        signal: dict,
    ) -> tuple[float, str] | None:
        if pos.side == "long":
            if signal["long_exit_tp"]:
                return signal["bb_upper"], "take_profit_bb"
            if signal["long_exit_stop"]:
                return signal["supertrend"], "stop_supertrend"
        else:
            if signal["short_exit_tp"]:
                return signal["bb_lower"], "take_profit_bb"
            if signal["short_exit_stop"]:
                return signal["supertrend"], "stop_supertrend"
        return None

    def tick(self) -> dict:
        df = fetch_ohlcv(
            symbol=self.symbol,
            timeframe=self.timeframe,
            limit=self.config.backtest.candles_limit,
            exchange=self._public_exchange,
        )
        htf_df = self._fetch_htf()
        signal = self.strategy.latest_signal(df, htf_df)
        action = "hold"

        pos = self._get_exchange_position()

        if pos is None:
            self._position_tick_count = 0
            self._last_bracket_prices = None
            if signal["long_signal"]:
                if self._open_position("long", signal):
                    action = "open_long"
            elif signal["short_signal"]:
                if self._open_position("short", signal):
                    action = "open_short"
        else:
            if self.live.place_bracket_orders:
                bracket_action = self._manage_bracket_orders(pos, signal)
                if bracket_action:
                    action = bracket_action
            else:
                exit_info = self._resolve_exit(pos, signal)
                if exit_info:
                    exit_price, exit_reason = exit_info
                    self._close_position(pos, signal, exit_price, exit_reason)
                    action = "close"

        return {
            "action": action,
            "signal": signal,
            "position": pos,
            "price": signal["close"],
        }

    def run(self) -> None:
        setup_logging()
        mode = self._mode_label
        try:
            self._log(
                f"{mode} | Hyperliquid | {self.symbol} {self.timeframe} | "
                f"leverage={self.live.leverage}x | size={self.live.position_size_pct*100:.0f}%"
                f" | leverage_sizing={'on' if self.live.use_leverage_for_sizing else 'off'}"
            )
            for warning in diagnose_wallet_setup():
                self._log(f"WARNING: {warning}")

            free, equity = self._get_balances()
            if not self.dry_run:
                self._log(f"Available USDC: ${free:.2f} | Equity: ${equity:.2f}")

            self._maybe_trade_analytics(force=True)

            self.notifier.notify_bot_started(
                mode=mode,
                symbol=self.symbol,
                timeframe=self.timeframe,
                exchange=self.config.exchange.id,
                balance_usd=free,
                equity_usd=equity,
            )

            while True:
                tick_started = time.monotonic()
                try:
                    status = call_with_timeout(self.tick, self.live.tick_timeout_sec)
                    side = status["position"].side.upper() if status["position"] else "FLAT"
                    elapsed = time.monotonic() - tick_started
                    self._log(
                        f"Price={status['price']:.2f} | Position={side} | "
                        f"Action={status['action']} | tick={elapsed:.1f}s"
                    )
                except TimeoutError as exc:
                    self._handle_tick_failure(exc, context="tick timeout")
                except Exception as exc:
                    self._handle_tick_failure(exc, context="tick")
                self._maybe_heartbeat()
                time.sleep(self.live.poll_interval_sec)
        except Exception as exc:
            self._report_error(exc, context="run")
            raise
