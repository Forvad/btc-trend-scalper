from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from src.backtest.live_like import bar_duration
from src.data.fetcher import fetch_ohlcv_max, fetch_ohlcv_range

if TYPE_CHECKING:
    from src.config import AppConfig


def intrabar_bars_per_htf(htf_timeframe: str, sub_timeframe: str) -> int:
    htf_minutes = bar_duration(htf_timeframe) / pd.Timedelta(minutes=1)
    sub_minutes = bar_duration(sub_timeframe) / pd.Timedelta(minutes=1)
    ratio = int(htf_minutes // sub_minutes)
    if ratio < 1:
        raise ValueError(
            f"Intrabar TF {sub_timeframe!r} must be smaller than HTF {htf_timeframe!r}"
        )
    return ratio


@dataclass(frozen=True)
class IntrabarAlignStats:
    htf_bars_before: int
    htf_bars_after: int
    intrabar_bars_before: int
    intrabar_bars_after: int
    range_start: pd.Timestamp
    range_end: pd.Timestamp
    dropped_htf_bars: int

    @property
    def days(self) -> int:
        return (self.range_end - self.range_start).days


def align_htf_to_intrabar(
    htf_df: pd.DataFrame,
    intrabar_df: pd.DataFrame,
    *,
    htf_timeframe: str,
    sub_timeframe: str,
    require_full_bars: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, IntrabarAlignStats]:
    """
    Обрезает HTF и intrabar до общего периода, где каждый HTF-бар
    полностью покрыт sub-TF свечами (для точного live-like).
    """
    if intrabar_df is None or intrabar_df.empty:
        raise ValueError("intrabar_df is empty — live-like требует sub-TF данные")

    htf = htf_df.sort_values("timestamp").reset_index(drop=True)
    ib = intrabar_df.sort_values("timestamp").reset_index(drop=True)

    bar_delta = bar_duration(htf_timeframe)
    bars_per_htf = intrabar_bars_per_htf(htf_timeframe, sub_timeframe)

    keep: list[int] = []
    for idx, row in htf.iterrows():
        bar_start = row["timestamp"]
        bar_end = bar_start + bar_delta
        sub = ib[(ib["timestamp"] >= bar_start) & (ib["timestamp"] < bar_end)]
        if require_full_bars:
            if len(sub) >= bars_per_htf:
                keep.append(idx)
        elif len(sub) > 0:
            keep.append(idx)

    if not keep:
        raise ValueError(
            "Нет HTF-баров с полным покрытием intrabar — проверьте диапазон загрузки"
        )

    htf_aligned = htf.loc[keep].reset_index(drop=True)
    range_start = htf_aligned["timestamp"].iloc[0]
    range_end = htf_aligned["timestamp"].iloc[-1] + bar_delta

    ib_aligned = ib[
        (ib["timestamp"] >= range_start) & (ib["timestamp"] < range_end)
    ].reset_index(drop=True)

    stats = IntrabarAlignStats(
        htf_bars_before=len(htf),
        htf_bars_after=len(htf_aligned),
        intrabar_bars_before=len(ib),
        intrabar_bars_after=len(ib_aligned),
        range_start=range_start,
        range_end=range_end,
        dropped_htf_bars=len(htf) - len(htf_aligned),
    )
    return htf_aligned, ib_aligned, stats


def fetch_intrabar_for_htf(
    symbol: str,
    htf_df: pd.DataFrame,
    *,
    htf_timeframe: str,
    sub_timeframe: str,
    exchange_id: str,
) -> pd.DataFrame:
    """Загрузить intrabar на календарный диапазон HTF (или MAX, если биржа не отдаёт)."""
    htf_start = htf_df["timestamp"].iloc[0]
    htf_until = htf_df["timestamp"].iloc[-1] + bar_duration(htf_timeframe)
    intrabar_df = fetch_ohlcv_range(
        symbol=symbol,
        timeframe=sub_timeframe,
        since=htf_start,
        until=htf_until,
        exchange_id=exchange_id,
    )
    if intrabar_df.empty:
        intrabar_df = fetch_ohlcv_max(
            symbol=symbol,
            timeframe=sub_timeframe,
            exchange_id=exchange_id,
        )
    return intrabar_df


def fetch_intrabar_for_backtest(
    config: AppConfig,
    htf_df: pd.DataFrame,
    *,
    htf_timeframe: str,
) -> pd.DataFrame:
    """Intrabar для live-like: отдельная биржа/символ из backtest-конфига."""
    sub_tf = config.backtest.intrabar_timeframe
    exchange_id = config.intrabar_exchange_id()
    symbol = config.intrabar_symbol()
    return fetch_intrabar_for_htf(
        symbol,
        htf_df,
        htf_timeframe=htf_timeframe,
        sub_timeframe=sub_tf,
        exchange_id=exchange_id,
    )


def prepare_live_like_data(
    htf_df: pd.DataFrame,
    intrabar_df: pd.DataFrame,
    *,
    htf_timeframe: str,
    sub_timeframe: str,
) -> tuple[pd.DataFrame, pd.DataFrame, IntrabarAlignStats]:
    """Выравнивает HTF и intrabar; бросает, если общего периода нет."""
    if intrabar_df.empty:
        raise ValueError(f"Нет данных intrabar ({sub_timeframe})")
    return align_htf_to_intrabar(
        htf_df,
        intrabar_df,
        htf_timeframe=htf_timeframe,
        sub_timeframe=sub_timeframe,
    )
