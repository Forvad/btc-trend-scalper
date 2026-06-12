import pandas as pd


def add_ema(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.DataFrame:
    result = df.copy()
    result["ema_fast"] = result["close"].ewm(span=fast, adjust=False).mean()
    result["ema_slow"] = result["close"].ewm(span=slow, adjust=False).mean()
    result["ema_cloud_top"] = result[["ema_fast", "ema_slow"]].max(axis=1)
    result["ema_cloud_bottom"] = result[["ema_fast", "ema_slow"]].min(axis=1)
    return result
