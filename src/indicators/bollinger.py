import pandas as pd


def add_bollinger_bands(
    df: pd.DataFrame,
    period: int = 20,
    std_dev: float = 2.0,
) -> pd.DataFrame:
    result = df.copy()
    sma = result["close"].rolling(window=period).mean()
    std = result["close"].rolling(window=period).std()
    result["bb_middle"] = sma
    result["bb_upper"] = sma + std_dev * std
    result["bb_lower"] = sma - std_dev * std
    return result
