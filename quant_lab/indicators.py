"""Causal indicators used by the BTC strategy research engine."""
from __future__ import annotations
import pandas as pd

def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")
    df = frame.copy()
    close = df["close"].astype(float)
    for period in (10, 20, 50, 100, 200):
        df[f"ema_{period}"] = close.ewm(span=period, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, float("nan"))
    df["rsi_14"] = (100 - 100 / (1 + rs)).mask((loss == 0) & (gain > 0), 100)
    prev = close.shift(1)
    tr = pd.concat([(df["high"]-df["low"]), (df["high"]-prev).abs(), (df["low"]-prev).abs()], axis=1).max(axis=1)
    df["atr_14"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    mid = close.rolling(20, min_periods=20).mean()
    std = close.rolling(20, min_periods=20).std(ddof=0)
    df["bb_upper"], df["bb_lower"] = mid + 2*std, mid - 2*std
    df["volume_sma_20"] = df["volume"].rolling(20, min_periods=20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_sma_20"].replace(0, float("nan"))
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    df["macd_hist"] = (fast-slow) - (fast-slow).ewm(span=9, adjust=False).mean()
    return df.replace([float("inf"), float("-inf")], float("nan"))
