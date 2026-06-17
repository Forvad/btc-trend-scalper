from __future__ import annotations

import copy
from dataclasses import dataclass, fields
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def _dataclass_from_dict(cls: type[T], raw: dict | None) -> T:
    """Создаёт dataclass, игнорируя неизвестные ключи (config новее кода в Docker)."""
    if not raw:
        return cls()
    allowed = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in allowed})

import yaml

from src.exchange.fees import FeeConfig, get_fee_preset


@dataclass
class SupertrendConfig:
    period: int = 10
    multiplier: float = 3.0


@dataclass
class BollingerConfig:
    period: int = 20
    std_dev: float = 2.0


@dataclass
class EnhancementConfig:
    enabled: bool = False
    entry_filter: bool = True
    min_potential_pct: float = 0.10
    require_ema_aligned: bool = True
    min_adx: float = 0.0
    adx_period: int = 14
    htf_filter: bool = False
    exit_partial_trail: bool = True
    partial_tp_pct: float = 0.50
    partial_at_middle: bool = True
    trail_breakeven_after_partial: bool = True
    smart_tp: bool = False
    trailing_activate_pct: float = 0.20

    def needs_adx(self) -> bool:
        return self.enabled and self.min_adx > 0

    def needs_htf(self) -> bool:
        return self.enabled and self.htf_filter


def v2_enhancement_config() -> EnhancementConfig:
    """Мягкий фильтр входа + partial @ BB middle + trail остатка."""
    return EnhancementConfig(
        enabled=True,
        entry_filter=True,
        min_potential_pct=0.10,
        require_ema_aligned=False,
        min_adx=0.0,
        htf_filter=False,
        exit_partial_trail=True,
        partial_tp_pct=0.50,
        partial_at_middle=True,
        trail_breakeven_after_partial=True,
        smart_tp=False,
        trailing_activate_pct=0.20,
    )


@dataclass
class RsiConfig:
    period: int = 14
    oversold: float = 35.0
    overbought: float = 65.0


@dataclass
class RangeAdxConfig:
    period: int = 14
    max_for_entry: float = 25.0
    emergency_exit: float = 27.0
    rising_emergency: float = 22.0


@dataclass
class SrFilterConfig:
    enabled: bool = False
    lookback: int = 100
    pivot_window: int = 3
    cluster_pct: float = 0.5


@dataclass
class RangeStrategyConfig:
    bollinger: BollingerConfig = None
    rsi: RsiConfig = None
    adx: RangeAdxConfig = None
    stop_loss_pct: float = 0.9
    use_swing_stop: bool = True
    swing_lookback: int = 5
    swing_buffer_pct: float = 0.15
    entry_mode: str = "bounce"
    take_profit: str = "middle_first"
    max_bb_width_pct: float = 0.0
    min_reward_to_middle_pct: float = 0.25
    require_rejection_candle: bool = True
    require_rsi_hook: bool = True
    require_adx_flat: bool = False
    block_counter_trend: bool = False
    counter_trend_adx: float = 18.0
    partial_at_middle_pct: float = 0.0
    cooldown_bars: int = 4
    sr_filter: SrFilterConfig = None

    def __post_init__(self) -> None:
        if self.bollinger is None:
            self.bollinger = BollingerConfig()
        if self.rsi is None:
            self.rsi = RsiConfig()
        if self.adx is None:
            self.adx = RangeAdxConfig()
        if self.sr_filter is None:
            self.sr_filter = SrFilterConfig()


@dataclass
class HybridConfig:
    """Режим рынка: trend при высоком ADX, range при низком."""

    trend_adx_min: float = 24.0
    range_adx_max: float = 22.0
    trend_always: bool = True

    def trend_regime(self, adx: float) -> bool:
        if self.trend_always:
            return True
        return adx >= self.trend_adx_min

    def range_regime(self, adx: float) -> bool:
        return adx <= self.range_adx_max


@dataclass
class TrailSlConfig:
    """
    Trail SL: до trail_start_at_pct — чистый supertrend.
    После — supertrend + шаги trail_step_pct.
    breakeven_at_pct > 0: пол на входе + шаги сверх порога.
    take_profit_bb: опциональный TP по Bollinger (как bracket).
    """

    enabled: bool = False
    trail_start_at_pct: float = 0.0
    breakeven_at_pct: float = 0.0
    trail_step_pct: float = 1.0
    take_profit_bb: bool = False


@dataclass
class StrategyConfig:
    ema_fast: int = 20
    ema_slow: int = 50
    supertrend: SupertrendConfig = None
    bollinger: BollingerConfig = None
    volume_sma_period: int = 20
    enhancements: EnhancementConfig = None
    trail_sl: TrailSlConfig = None

    def __post_init__(self) -> None:
        if self.supertrend is None:
            self.supertrend = SupertrendConfig()
        if self.bollinger is None:
            self.bollinger = BollingerConfig()
        if self.enhancements is None:
            self.enhancements = EnhancementConfig()
        if self.trail_sl is None:
            self.trail_sl = TrailSlConfig()


@dataclass
class ExchangeConfig:
    id: str = "hyperliquid"
    symbol: str = "BTC/USDC:USDC"
    fee_preset: str = "hyperliquid"
    fees: FeeConfig = None

    def __post_init__(self) -> None:
        if self.fees is None:
            self.fees = get_fee_preset(self.fee_preset)


@dataclass
class BacktestConfig:
    initial_balance: float = 10_000.0
    position_size_pct: float = 0.95
    candles_limit: int = 1000
    live_like: bool = True
    intrabar_timeframe: str = "5m"


@dataclass
class PaperConfig:
    poll_interval_sec: int = 60
    initial_balance: float = 10_000.0
    position_size_pct: float = 0.95
    api_timeout_sec: int = 30
    tick_timeout_sec: int = 90
    heartbeat_interval_sec: int = 900


@dataclass
class NotificationsConfig:
    enabled: bool = True
    notify_on_start: bool = True
    notify_on_trade: bool = True
    notify_on_error: bool = True


# обратная совместимость
TelegramConfig = NotificationsConfig


@dataclass
class LiveConfig:
    poll_interval_sec: int = 60
    position_size_pct: float = 0.95
    use_leverage_for_sizing: bool = False
    leverage: int = 1
    margin_mode: str = "cross"
    slippage: float = 0.001
    min_notional_usd: float = 10.0
    max_notional_usd: float = 100_000.0
    place_bracket_orders: bool = True
    update_bracket_orders: bool = True
    bracket_update_every_ticks: int = 10
    bracket_tp_min_change_pct: float = 0.5
    bracket_tp_min_change_ticks: int = 0
    # dynamic — TP следует за BB в обе стороны; tighten — только ближе к цене; freeze — TP с входа
    bracket_tp_mode: str = "tighten"
    api_timeout_sec: int = 30
    tick_timeout_sec: int = 90
    heartbeat_interval_sec: int = 900
    trade_analytics_enabled: bool = True
    trade_analytics_days: int = 30
    trade_analytics_interval_sec: int = 0  # 0 — только при старте; >0 — повтор в heartbeat
    min_sl_distance_pct: float = 1.0  # мин. дистанция SL от цены входа (%)


@dataclass
class AppConfig:
    bot: str = "trend"
    default_timeframe: str = "15m"
    exchange: ExchangeConfig = None
    timeframes: list[str] = None
    strategy: StrategyConfig = None
    strategy_by_timeframe: dict[str, StrategyConfig] = None
    range_strategy: RangeStrategyConfig = None
    hybrid: HybridConfig = None
    backtest: BacktestConfig = None
    paper: PaperConfig = None
    live: LiveConfig = None
    notifications: NotificationsConfig = None

    def __post_init__(self) -> None:
        if self.exchange is None:
            self.exchange = ExchangeConfig()
        if self.timeframes is None:
            self.timeframes = ["15m", "1h"]
        if self.strategy is None:
            self.strategy = StrategyConfig()
        if self.strategy_by_timeframe is None:
            self.strategy_by_timeframe = {}
        if self.range_strategy is None:
            self.range_strategy = RangeStrategyConfig()
        if self.hybrid is None:
            self.hybrid = HybridConfig()
        if self.backtest is None:
            self.backtest = BacktestConfig()
        if self.paper is None:
            self.paper = PaperConfig()
        if self.live is None:
            self.live = LiveConfig()
        if self.notifications is None:
            self.notifications = NotificationsConfig()

    @property
    def symbol(self) -> str:
        return self.exchange.symbol

    def strategy_for_timeframe(self, timeframe: str) -> StrategyConfig:
        return self.strategy_by_timeframe.get(timeframe, self.strategy)


def _load_fees(raw_fees: dict | None, preset: str) -> FeeConfig:
    base = get_fee_preset(preset)
    if not raw_fees:
        return base
    return FeeConfig(
        maker_pct=raw_fees.get("maker_pct", base.maker_pct),
        taker_pct=raw_fees.get("taker_pct", base.taker_pct),
        entry=raw_fees.get("entry", base.entry),
        exit_stop=raw_fees.get("exit_stop", base.exit_stop),
        exit_tp=raw_fees.get("exit_tp", base.exit_tp),
    )


def _load_range_strategy(raw: dict) -> RangeStrategyConfig:
    rsi = raw.get("rsi", {})
    adx = raw.get("adx", {})
    sr = raw.get("sr_filter", {})
    defaults = RangeStrategyConfig()
    return RangeStrategyConfig(
        bollinger=BollingerConfig(**raw.get("bollinger", {})),
        rsi=RsiConfig(**rsi) if rsi else RsiConfig(),
        adx=RangeAdxConfig(**adx) if adx else RangeAdxConfig(),
        stop_loss_pct=raw.get("stop_loss_pct", defaults.stop_loss_pct),
        use_swing_stop=raw.get("use_swing_stop", defaults.use_swing_stop),
        swing_lookback=raw.get("swing_lookback", defaults.swing_lookback),
        swing_buffer_pct=raw.get("swing_buffer_pct", defaults.swing_buffer_pct),
        entry_mode=raw.get("entry_mode", defaults.entry_mode),
        take_profit=raw.get("take_profit", defaults.take_profit),
        max_bb_width_pct=raw.get("max_bb_width_pct", defaults.max_bb_width_pct),
        min_reward_to_middle_pct=raw.get(
            "min_reward_to_middle_pct", defaults.min_reward_to_middle_pct
        ),
        require_rejection_candle=raw.get(
            "require_rejection_candle", defaults.require_rejection_candle
        ),
        require_rsi_hook=raw.get("require_rsi_hook", defaults.require_rsi_hook),
        require_adx_flat=raw.get("require_adx_flat", defaults.require_adx_flat),
        block_counter_trend=raw.get("block_counter_trend", defaults.block_counter_trend),
        counter_trend_adx=raw.get("counter_trend_adx", defaults.counter_trend_adx),
        partial_at_middle_pct=raw.get("partial_at_middle_pct", defaults.partial_at_middle_pct),
        cooldown_bars=raw.get("cooldown_bars", defaults.cooldown_bars),
        sr_filter=SrFilterConfig(**sr) if sr else SrFilterConfig(),
    )


def _load_strategy(st: dict, *, base: StrategyConfig | None = None) -> StrategyConfig:
    if base is None:
        base = StrategyConfig()
    enh_raw = st.get("enhancements")
    enh = (
        EnhancementConfig(**enh_raw)
        if enh_raw is not None
        else copy.deepcopy(base.enhancements)
    )
    st_cfg = st.get("supertrend")
    bb_cfg = st.get("bollinger")
    trail_raw = st.get("trail_sl")
    if trail_raw is not None:
        trail = TrailSlConfig(**dict(trail_raw))
    else:
        trail = copy.deepcopy(base.trail_sl)
    return StrategyConfig(
        ema_fast=st.get("ema_fast", base.ema_fast),
        ema_slow=st.get("ema_slow", base.ema_slow),
        supertrend=SupertrendConfig(**st_cfg) if st_cfg else copy.deepcopy(base.supertrend),
        bollinger=BollingerConfig(**bb_cfg) if bb_cfg else copy.deepcopy(base.bollinger),
        volume_sma_period=st.get("volume_sma_period", base.volume_sma_period),
        enhancements=enh,
        trail_sl=trail,
    )


def _load_strategy_by_timeframe(
    raw: dict | None,
    base: StrategyConfig,
) -> dict[str, StrategyConfig]:
    if not raw:
        return {}
    return {tf: _load_strategy(overrides, base=base) for tf, overrides in raw.items()}


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        return AppConfig()

    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    ex = raw.get("exchange", {})
    bt = raw.get("backtest", {})
    pp = raw.get("paper", {})
    lv = raw.get("live", {})
    notify_raw = raw.get("notifications") or raw.get("telegram", {})
    hy = raw.get("hybrid", {})

    fee_preset = ex.get("fee_preset", "hyperliquid")
    exchange = ExchangeConfig(
        id=ex.get("id", "hyperliquid"),
        symbol=ex.get("symbol", "BTC/USDC:USDC"),
        fee_preset=fee_preset,
        fees=_load_fees(ex.get("fees"), fee_preset),
    )

    if "symbol" in raw:
        exchange.symbol = raw["symbol"]

    strategy = _load_strategy(raw.get("strategy", {}))
    return AppConfig(
        bot=raw.get("bot", "trend"),
        default_timeframe=raw.get("default_timeframe", "15m"),
        exchange=exchange,
        timeframes=raw.get("timeframes", ["15m", "1h"]),
        strategy=strategy,
        strategy_by_timeframe=_load_strategy_by_timeframe(
            raw.get("strategy_by_timeframe"), strategy
        ),
        range_strategy=_load_range_strategy(raw.get("range_strategy", {})),
        hybrid=_dataclass_from_dict(HybridConfig, hy),
        backtest=_dataclass_from_dict(BacktestConfig, bt),
        paper=_dataclass_from_dict(PaperConfig, pp),
        live=_dataclass_from_dict(LiveConfig, lv),
        notifications=_dataclass_from_dict(NotificationsConfig, notify_raw),
    )
