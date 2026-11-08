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
    # Explicit crossover events: true only on the candle where the relationship flips.
    for fast_period, slow_period in ((10, 20), (20, 50), (50, 200)):
        fast_line, slow_line = df[f"ema_{fast_period}"], df[f"ema_{slow_period}"]
        cross_up = (fast_line.shift(1) <= slow_line.shift(1)) & (fast_line > slow_line)
        cross_down = (fast_line.shift(1) >= slow_line.shift(1)) & (fast_line < slow_line)
        df[f"ema_{fast_period}_cross_up_ema_{slow_period}"] = cross_up.astype(float)
        df[f"ema_{fast_period}_cross_down_ema_{slow_period}"] = cross_down.astype(float)
    # Exchange-local opening events; zoneinfo handles daylight-saving changes.
    if "open_time" in df.columns:
        utc_times = pd.to_datetime(df["open_time"], utc=True)
        sessions = (
            ("asia", "Asia/Tokyo", "09:00"),
            ("london", "Europe/London", "08:00"),
            ("new_york", "America/New_York", "09:30"),
        )
        for label, zone, opening in sessions:
            local = utc_times.dt.tz_convert(zone)
            hour, minute = (int(part) for part in opening.split(":"))
            df[f"session_{label}_open"] = ((local.dt.hour == hour) & (local.dt.minute == minute)).astype(float)
    else:
        for label in ("asia", "london", "new_york"):
            df[f"session_{label}_open"] = 0.0
    return df.replace([float("inf"), float("-inf")], float("nan"))
