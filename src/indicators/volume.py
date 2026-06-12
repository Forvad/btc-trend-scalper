import pandas as pd


def add_volume_sma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    result = df.copy()
    result["volume_sma"] = result["volume"].rolling(window=period).mean()
    return result
