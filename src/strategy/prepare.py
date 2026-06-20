import pandas as pd

from src.config import StrategyConfig
from src.indicators import add_adx, add_bollinger_bands, add_ema, add_supertrend, add_volume_sma


def prepare_dataframe(df: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    result = add_ema(df, config.ema_fast, config.ema_slow)
    result = add_supertrend(
        result,
        period=config.supertrend.period,
        multiplier=config.supertrend.multiplier,
    )
    result = add_bollinger_bands(
        result,
        period=config.bollinger.period,
        std_dev=config.bollinger.std_dev,
    )
    result = add_volume_sma(result, config.volume_sma_period)
    adx_period = 14
    if config.adx_filter.enabled:
        adx_period = config.adx_filter.period
    elif config.enhancements.needs_adx():
        adx_period = config.enhancements.adx_period
    if config.adx_filter.enabled or config.enhancements.needs_adx():
        result = add_adx(result, adx_period)
    return result
