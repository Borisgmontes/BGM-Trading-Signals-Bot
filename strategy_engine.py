"""Rule-block signal engine for user-defined BGM sub-strategies.

Uses closed public spot candles. It only generates informational alerts; it never places orders.
"""
import logging
import requests
import pandas as pd

BASE_URL = "https://api.binance.us/api/v3/klines"
ALLOWED_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT"}
ALLOWED_TIMEFRAMES = {"5m", "15m", "1h", "4h"}
ENTRY_TYPES = {"breakout", "ema_cross", "liquidity_sweep", "bos"}
TREND_FILTERS = {"none", "ema200", "ema_alignment"}
CONFIRMATIONS = {"none", "volume", "atr"}
STOP_TYPES = {"atr", "swing", "fixed_pct"}
TARGET_R = {1.5, 2.0, 3.0}
log = logging.getLogger("BGM.strategy")


def validate_config(config):
    if config.get("symbol") not in ALLOWED_SYMBOLS:
        raise ValueError("Activo no permitido. Usa BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, ADAUSDT o DOGEUSDT.")
    if config.get("timeframe") not in ALLOWED_TIMEFRAMES:
        raise ValueError("Temporalidad no válida. Usa 5m, 15m, 1h o 4h.")
    if config.get("entry") not in ENTRY_TYPES:
        raise ValueError("Entrada no válida: breakout, ema_cross, liquidity_sweep o bos.")
    if config.get("trend") not in TREND_FILTERS:
        raise ValueError("Filtro de tendencia no válido: none, ema200 o ema_alignment.")
    if config.get("confirmation") not in CONFIRMATIONS:
        raise ValueError("Confirmación no válida: none, volume o atr.")
    if config.get("stop") not in STOP_TYPES:
        raise ValueError("Stop no válido: atr, swing o fixed_pct.")
    if float(config.get("risk_pct", 0)) not in (0.25, 0.5, 1.0, 2.0):
        raise ValueError("Riesgo permitido: 0.25, 0.5, 1 o 2 (%).")
    if float(config.get("target_r", 0)) not in TARGET_R:
        raise ValueError("Objetivo permitido: 1.5R, 2R o 3R.")
    return config


def fetch_candles(symbol, timeframe, limit=260):
    response = requests.get(BASE_URL, params={"symbol": symbol, "interval": timeframe, "limit": limit},
                            headers={"User-Agent": "BGM-Trading-Signals/2.0"}, timeout=15)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or len(rows) < 220:
        raise ValueError(f"Datos insuficientes para {symbol} {timeframe}")
    columns = ["open_time", "open", "high", "low", "close", "volume", "close_time",
               "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
    df = pd.DataFrame(rows, columns=columns)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    df = df.dropna().iloc[:-1].reset_index(drop=True)  # exclude still-open candle
    for period in (20, 50, 200):
        df[f"ema{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    previous = df["close"].shift(1)
    tr = pd.concat([(df["high"]-df["low"]), (df["high"]-previous).abs(),
                    (df["low"]-previous).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    return df.dropna().reset_index(drop=True)


def evaluate(df, config):
    """Return (candle_id, signal-or-None). Rules are deliberately transparent."""
    if len(df) < 205:
        return None, None
    cur = df.iloc[-1]
    prev = df.iloc[-2]
    history = df.iloc[-21:-1]
    entry_rule = config["entry"]
    long_entry = short_entry = False

    if entry_rule == "breakout":
        long_entry = cur["close"] > history["high"].max()
        short_entry = cur["close"] < history["low"].min()
    elif entry_rule == "ema_cross":
        long_entry = prev["ema20"] <= prev["ema50"] and cur["ema20"] > cur["ema50"]
        short_entry = prev["ema20"] >= prev["ema50"] and cur["ema20"] < cur["ema50"]
    elif entry_rule == "liquidity_sweep":
        recent = df.iloc[-11:-1]
        long_entry = cur["low"] < recent["low"].min() and cur["close"] > recent["low"].min()
        short_entry = cur["high"] > recent["high"].max() and cur["close"] < recent["high"].max()
    elif entry_rule == "bos":
        long_entry = cur["close"] > history["high"].max()
        short_entry = cur["close"] < history["low"].min()

    trend = config["trend"]
    if trend == "ema200":
        long_entry = bool(long_entry and cur["close"] > cur["ema200"])
        short_entry = bool(short_entry and cur["close"] < cur["ema200"])
    elif trend == "ema_alignment":
        long_entry = bool(long_entry and cur["ema20"] > cur["ema50"] > cur["ema200"])
        short_entry = bool(short_entry and cur["ema20"] < cur["ema50"] < cur["ema200"])

    confirmation = config["confirmation"]
    if confirmation == "volume":
        ok = cur["volume"] >= cur["vol_sma20"]
        long_entry = bool(long_entry and ok)
        short_entry = bool(short_entry and ok)
    elif confirmation == "atr":
        ok = (cur["high"] - cur["low"]) >= 0.5 * cur["atr"]
        long_entry = bool(long_entry and ok)
        short_entry = bool(short_entry and ok)

    if not long_entry and not short_entry:
        return str(int(cur["open_time"])), None

    direction = "LONG" if long_entry else "SHORT"
    entry = float(cur["close"])
    atr = float(cur["atr"])
    if config["stop"] == "atr":
        distance = 1.5 * atr
    elif config["stop"] == "swing":
        distance = max(entry - float(df.iloc[-6:]["low"].min()), 0) if direction == "LONG" else max(float(df.iloc[-6:]["high"].max()) - entry, 0)
        distance = max(distance, 0.1 * atr)
    else:
        distance = entry * 0.005
    stop = entry - distance if direction == "LONG" else entry + distance
    rr = float(config["target_r"])
    target = entry + rr * distance if direction == "LONG" else entry - rr * distance
    candle_id = str(int(cur["open_time"]))
    return candle_id, {
        "symbol": config["symbol"], "timeframe": config["timeframe"], "direction": direction,
        "entry": entry, "stop": stop, "target": target, "rr": rr,
        "risk_pct": float(config["risk_pct"]), "candle_id": candle_id,
        "strategy_name": config.get("name", "Subestrategia")
    }


def format_alert(signal):
    side = "🟢 LONG" if signal["direction"] == "LONG" else "🔴 SHORT"
    return (
        "⚡ BGM TRADING SIGNALS — SUBESTRATEGIA\n\n"
        f"Nombre: {signal['strategy_name']}\n"
        f"{side} | {signal['symbol']} | {signal['timeframe']}\n"
        f"Entrada de referencia: {signal['entry']:.8g}\n"
        f"Stop Loss: {signal['stop']:.8g}\n"
        f"Take Profit: {signal['target']:.8g}\n"
        f"Objetivo teórico: {signal['rr']:.1f}R\n"
        f"Riesgo configurado: {signal['risk_pct']:.2f}% (no garantiza la pérdida real)\n"
        f"Vela cerrada UTC: {signal['candle_id']}\n\n"
        "Datos públicos spot. Alerta informativa; no ejecuta órdenes y no garantiza rentabilidad."
    )
