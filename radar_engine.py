"""Configurable BTC confluence radar. Closed-candle, informational alerts only."""
import pandas as pd
import requests

BASE_URL = "https://api.binance.us/api/v3/klines"
ALLOWED_TF = {"5m", "15m", "1h", "4h"}
MODULES = {"trend", "rsi", "macd", "volume", "atr", "bollinger", "liquidity", "bos"}


def validate_radar_config(config):
    if config.get("symbol") != "BTCUSDT":
        raise ValueError("BTC Radar trabaja inicialmente con BTCUSDT.")
    if config.get("timeframe") not in ALLOWED_TF:
        raise ValueError("Temporalidad no válida.")
    modules = config.get("modules")
    if not isinstance(modules, list) or not modules or not set(modules).issubset(MODULES):
        raise ValueError("Selecciona al menos un módulo válido.")
    score = int(config.get("min_score", 3))
    if score < 1 or score > len(modules):
        raise ValueError("Las confirmaciones mínimas deben estar entre 1 y los módulos activos.")
    rr = float(config.get("target_r", 2.0))
    if rr not in (1.5, 2.0, 3.0):
        raise ValueError("Objetivo permitido: 1.5R, 2R o 3R.")
    return config


def fetch_radar_candles(symbol, timeframe, limit=1000):
    response = requests.get(BASE_URL, params={"symbol": symbol, "interval": timeframe, "limit": limit},
                            headers={"User-Agent": "BGM-BTC-Radar/1.0"}, timeout=15)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or len(rows) < 220:
        raise ValueError(f"Datos insuficientes para {symbol} {timeframe}")
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
    df = pd.DataFrame(rows, columns=cols)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    df = df.dropna().iloc[:-1].reset_index(drop=True)  # only completed candles
    for period in (20, 50, 200):
        df[f"ema{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100)
    rsi = rsi.mask((gain == 0) & (loss > 0), 0)
    df["rsi"] = rsi.fillna(50)
    fast = df["close"].ewm(span=12, adjust=False).mean()
    slow = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = fast - slow
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    prev = df["close"].shift(1)
    tr = pd.concat([(df["high"] - df["low"]), (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    mid = df["close"].rolling(20).mean()
    std = df["close"].rolling(20).std(ddof=0)
    df["bb_upper"] = mid + 2 * std
    df["bb_lower"] = mid - 2 * std
    return df.dropna().reset_index(drop=True)


def evaluate_radar(df, config):
    """Score directional confirmations on the latest closed candle."""
    if len(df) < 205:
        return None, None
    cur, prev = df.iloc[-1], df.iloc[-2]
    history = df.iloc[-21:-1]
    modules = set(config["modules"])
    long_checks, short_checks = {}, {}
    if "trend" in modules:
        long_checks["Tendencia EMA"] = cur["close"] > cur["ema200"] and cur["ema20"] > cur["ema50"]
        short_checks["Tendencia EMA"] = cur["close"] < cur["ema200"] and cur["ema20"] < cur["ema50"]
    if "rsi" in modules:
        long_checks["RSI"] = 50 < cur["rsi"] < 70
        short_checks["RSI"] = 30 < cur["rsi"] < 50
    if "macd" in modules:
        long_checks["MACD"] = cur["macd_hist"] > 0 and cur["macd_hist"] >= prev["macd_hist"]
        short_checks["MACD"] = cur["macd_hist"] < 0 and cur["macd_hist"] <= prev["macd_hist"]
    if "volume" in modules:
        volume_ok = cur["volume"] >= cur["vol_sma20"]
        long_checks["Volumen"] = bool(volume_ok and cur["close"] >= cur["open"])
        short_checks["Volumen"] = bool(volume_ok and cur["close"] <= cur["open"])
    if "atr" in modules:
        atr_ok = (cur["high"] - cur["low"]) >= 0.5 * cur["atr"]
        long_checks["Rango/ATR"] = bool(atr_ok and cur["close"] >= cur["open"])
        short_checks["Rango/ATR"] = bool(atr_ok and cur["close"] <= cur["open"])
    if "bollinger" in modules:
        long_checks["Bollinger"] = cur["close"] > cur["bb_upper"]
        short_checks["Bollinger"] = cur["close"] < cur["bb_lower"]
    if "liquidity" in modules:
        low_ref, high_ref = history["low"].min(), history["high"].max()
        long_checks["Barrido de liquidez"] = cur["low"] < low_ref and cur["close"] > low_ref
        short_checks["Barrido de liquidez"] = cur["high"] > high_ref and cur["close"] < high_ref
    if "bos" in modules:
        long_checks["BOS"] = cur["close"] > history["high"].max()
        short_checks["BOS"] = cur["close"] < history["low"].min()

    long_score = sum(bool(v) for v in long_checks.values())
    short_score = sum(bool(v) for v in short_checks.values())
    minimum = int(config["min_score"])
    direction = "LONG" if long_score >= minimum and long_score > short_score else (
        "SHORT" if short_score >= minimum and short_score > long_score else None)
    candle_id = str(int(cur["open_time"]))
    if not direction:
        return candle_id, None

    entry = float(cur["close"])
    atr = float(cur["atr"])
    stop_distance = max(1.5 * atr, entry * 0.001)
    stop = entry - stop_distance if direction == "LONG" else entry + stop_distance
    rr = float(config.get("target_r", 2.0))
    target = entry + rr * stop_distance if direction == "LONG" else entry - rr * stop_distance
    checks = long_checks if direction == "LONG" else short_checks
    score = long_score if direction == "LONG" else short_score
    confirmations = [name for name, passed in checks.items() if passed]
    return candle_id, {
        "symbol": "BTCUSDT", "timeframe": config["timeframe"], "direction": direction,
        "entry": entry, "stop": stop, "target": target, "rr": rr,
        "score": score, "maximum": len(modules), "confirmations": confirmations,
        "candle_id": candle_id, "strategy_name": config.get("name", "BTC RADAR"),
    }


def format_radar_alert(signal):
    side = "🟢 LONG" if signal["direction"] == "LONG" else "🔴 SHORT"
    confirmations = "\n".join("• " + item for item in signal["confirmations"])
    return (
        "📡 BTC RADAR — BGM SIGNALS\n\n"
        f"{side} | {signal['symbol']} | {signal['timeframe']}\n"
        f"Confluencias: {signal['score']}/{signal['maximum']}\n\n"
        f"Entrada de referencia: {signal['entry']:.8g}\n"
        f"Stop Loss: {signal['stop']:.8g}\n"
        f"Take Profit: {signal['target']:.8g}\n"
        f"Objetivo teórico: {signal['rr']:.1f}R\n\n"
        f"Confirmaciones:\n{confirmations}\n\n"
        f"Vela cerrada UTC: {signal['candle_id']}\n"
        "Datos spot públicos. Alerta informativa; no ejecuta órdenes ni garantiza resultados."
    )


def estimate_probability(df, config, direction, horizon=20, min_samples=30):
    """Historical TP-before-SL rate for the same radar setup and direction.

    Uses only signals generated from candles before their outcomes. If fewer than
    min_samples historical examples exist, returns None instead of a fake number.
    A candle touching TP and SL together is counted as an SL (conservative).
    """
    if len(df) < 205 + horizon + min_samples:
        return None
    wins = 0
    samples = 0
    last_signal_index = len(df) - horizon - 1
    for i in range(204, last_signal_index + 1):
        _, historical = evaluate_radar(df.iloc[:i + 1], config)
        if not historical or historical["direction"] != direction:
            continue
        future = df.iloc[i + 1:i + horizon + 1]
        hit = False
        won = False
        for _, candle in future.iterrows():
            if direction == "LONG":
                stop_hit = float(candle["low"]) <= historical["stop"]
                target_hit = float(candle["high"]) >= historical["target"]
            else:
                stop_hit = float(candle["high"]) >= historical["stop"]
                target_hit = float(candle["low"]) <= historical["target"]
            if stop_hit or target_hit:
                hit = True
                won = bool(target_hit and not stop_hit)
                break
        samples += 1
        if hit and won:
            wins += 1
    if samples < min_samples:
        return None
    return round(100 * wins / samples)
