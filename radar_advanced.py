"""Advanced, deterministic BTC radar features.

All detections use closed candles only. Pattern detection is intentionally
rule-based and explainable; it does not claim predictive certainty.
"""
import pandas as pd


ADVANCED_MODULES = {
    "adx", "vwap", "obv", "stochastic", "supertrend", "divergence",
    "fibonacci", "chart_patterns", "fvg", "order_blocks", "fakeout",
}


def add_advanced_indicators(df):
    out = df.copy()
    high, low, close, volume = out["high"], out["low"], out["close"], out["volume"]
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    up = high.diff()
    down = -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    atr14 = tr.rolling(14).mean()
    plus_di = 100 * plus_dm.rolling(14).mean() / atr14.replace(0, pd.NA)
    minus_di = 100 * minus_dm.rolling(14).mean() / atr14.replace(0, pd.NA)
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, pd.NA)
    out["adx"] = dx.rolling(14).mean()
    typical = (high + low + close) / 3
    session = pd.to_datetime(out["open_time"], unit="ms", utc=True).dt.floor("D")
    pv = typical * volume
    out["vwap"] = pv.groupby(session).cumsum() / volume.groupby(session).cumsum().replace(0, pd.NA)
    signed_volume = volume.where(close > prev_close, -volume.where(close < prev_close, 0))
    out["obv"] = signed_volume.fillna(0).cumsum()
    lowest = low.rolling(14).min()
    highest = high.rolling(14).max()
    out["stoch_k"] = 100 * (close-lowest) / (highest-lowest).replace(0, pd.NA)
    out["stoch_d"] = out["stoch_k"].rolling(3).mean()
    mid = (high + low) / 2
    upper = mid + 3 * atr14
    lower = mid - 3 * atr14
    st = pd.Series(index=out.index, dtype=float)
    direction = pd.Series(index=out.index, dtype=int)
    for i in range(len(out)):
        if i == 0 or pd.isna(atr14.iloc[i]):
            st.iloc[i] = lower.iloc[i]
            direction.iloc[i] = 1
            continue
        prior_dir = int(direction.iloc[i-1])
        if close.iloc[i] > upper.iloc[i-1]:
            direction.iloc[i] = 1
        elif close.iloc[i] < lower.iloc[i-1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = prior_dir
        st.iloc[i] = lower.iloc[i] if direction.iloc[i] == 1 else upper.iloc[i]
    out["supertrend"] = st
    out["supertrend_dir"] = direction
    return out


def _swing_points(df, left=3, right=3):
    highs, lows = [], []
    for i in range(left, len(df)-right):
        window = df.iloc[i-left:i+right+1]
        if df["high"].iloc[i] == window["high"].max():
            highs.append((i, float(df["high"].iloc[i])))
        if df["low"].iloc[i] == window["low"].min():
            lows.append((i, float(df["low"].iloc[i])))
    return highs, lows


def detect_fibonacci(df):
    highs, lows = _swing_points(df.tail(120).reset_index(drop=True), 3, 3)
    if not highs or not lows:
        return {}
    hi_i, hi = highs[-1]
    lo_i, lo = lows[-1]
    if hi_i > lo_i:
        return {str(level): hi - (hi-lo)*level for level in (0.382, 0.5, 0.618, 0.786)}
    return {str(level): lo + (hi-lo)*level for level in (0.382, 0.5, 0.618, 0.786)}


def detect_chart_patterns(df):
    """Conservative simple patterns from confirmed local extrema."""
    highs, lows = _swing_points(df.tail(100).reset_index(drop=True), 2, 2)
    result = []
    if len(highs) >= 2:
        a, b = highs[-2][1], highs[-1][1]
        if abs(a-b) / max(a, b) < 0.008:
            result.append("DOBLE_TECHO")
    if len(lows) >= 2:
        a, b = lows[-2][1], lows[-1][1]
        if abs(a-b) / max(a, b) < 0.008:
            result.append("DOBLE_SUELO")
    if len(highs) >= 2 and len(lows) >= 2:
        h1, h2 = highs[-2][1], highs[-1][1]
        l1, l2 = lows[-2][1], lows[-1][1]
        if h2 < h1 and l2 > l1:
            result.append("TRIANGULO_SIMETRICO")
    return result


def advanced_checks(df, enabled):
    """Return directional boolean checks and metadata for the latest closed bar."""
    if not enabled:
        return {}, {}, {}
    cur, prev = df.iloc[-1], df.iloc[-2]
    long_checks, short_checks, meta = {}, {}, {}
    if "adx" in enabled:
        strong = float(cur.get("adx", 0) or 0) >= 20
        long_checks["ADX"] = bool(strong and cur["close"] > cur["ema50"])
        short_checks["ADX"] = bool(strong and cur["close"] < cur["ema50"])
    if "vwap" in enabled:
        long_checks["VWAP"] = bool(cur["close"] > cur.get("vwap", float("inf")))
        short_checks["VWAP"] = bool(cur["close"] < cur.get("vwap", float("-inf")))
    if "obv" in enabled:
        long_checks["OBV"] = bool(cur.get("obv", 0) > prev.get("obv", 0))
        short_checks["OBV"] = bool(cur.get("obv", 0) < prev.get("obv", 0))
    if "stochastic" in enabled:
        long_checks["Stochastic"] = bool(cur.get("stoch_k", 50) > cur.get("stoch_d", 50) and cur.get("stoch_k", 50) < 80)
        short_checks["Stochastic"] = bool(cur.get("stoch_k", 50) < cur.get("stoch_d", 50) and cur.get("stoch_k", 50) > 20)
    if "supertrend" in enabled:
        long_checks["Supertrend"] = int(cur.get("supertrend_dir", 0)) == 1
        short_checks["Supertrend"] = int(cur.get("supertrend_dir", 0)) == -1
    if "fvg" in enabled:
        long_checks["FVG alcista"] = float(cur["low"]) > float(df.iloc[-3]["high"])
        short_checks["FVG bajista"] = float(cur["high"]) < float(df.iloc[-3]["low"])
    if "fakeout" in enabled:
        ref = df.iloc[-21:-1]
        long_checks["Fakeout bajista"] = bool(cur["low"] < ref["low"].min() and cur["close"] > ref["low"].min())
        short_checks["Fakeout alcista"] = bool(cur["high"] > ref["high"].max() and cur["close"] < ref["high"].max())
    if "fibonacci" in enabled:
        levels = detect_fibonacci(df)
        meta["fibonacci_levels"] = levels
        tolerance = float(cur["atr"]) * 0.35
        near = [v for v in levels.values() if abs(float(cur["close"])-v) <= tolerance]
        long_checks["Confluencia Fibonacci"] = bool(near and cur["close"] >= cur["open"])
        short_checks["Confluencia Fibonacci"] = bool(near and cur["close"] <= cur["open"])
    if "chart_patterns" in enabled:
        patterns = detect_chart_patterns(df)
        meta["chart_patterns"] = patterns
        long_checks["Patrón chartista"] = any(p in patterns for p in ("DOBLE_SUELO",))
        short_checks["Patrón chartista"] = any(p in patterns for p in ("DOBLE_TECHO",))
    if "order_blocks" in enabled:
        # Proxy rule: last opposite candle before a displacement candle.
        prior = df.iloc[-4:-1]
        bullish = prior[(prior["close"] < prior["open"])]
        bearish = prior[(prior["close"] > prior["open"])]
        long_checks["Order Block"] = bool(len(bullish) and cur["close"] > bullish.iloc[-1]["high"])
        short_checks["Order Block"] = bool(len(bearish) and cur["close"] < bearish.iloc[-1]["low"])
    return long_checks, short_checks, meta
