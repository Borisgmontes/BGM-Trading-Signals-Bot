import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

BASE_URL = "https://fapi.binance.com/fapi/v1/klines"
SYMBOLS = [s.strip().upper() for s in os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT").split(",") if s.strip()]
RISK_PCT = float(os.getenv("RISK_PCT", "0.01"))
MIN_RR = float(os.getenv("MIN_RR", "2.0"))
ACCOUNT_EQUITY = float(os.getenv("ACCOUNT_EQUITY_USDT", "0") or 0)
STATE_FILE = Path(os.getenv("STATE_FILE", "signal_state.json"))
HEADERS = {"User-Agent": "BGM-Trading-Signals/1.0"}

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("BGM")


def fetch_klines(symbol: str, interval: str, limit: int = 250) -> pd.DataFrame:
    response = requests.get(BASE_URL, params={"symbol": symbol, "interval": interval, "limit": limit}, headers=HEADERS, timeout=15)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or len(rows) < 220:
        raise ValueError(f"Datos insuficientes para {symbol} {interval}")
    cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
            "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
    df = pd.DataFrame(rows, columns=cols)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce").astype("int64")
    return df.iloc[:-1].dropna().reset_index(drop=True)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for period in (20, 50, 200):
        df[f"ema{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    previous_close = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - previous_close).abs(),
                    (df["low"] - previous_close).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["vol_sma20"] = df["volume"].rolling(20).mean()
    return df.dropna().reset_index(drop=True)


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def detect_signal(symbol: str):
    h4 = add_indicators(fetch_klines(symbol, "4h"))
    h1 = add_indicators(fetch_klines(symbol, "1h"))
    if len(h1) < 30 or len(h4) < 5:
        return None, None

    bias = h4.iloc[-1]
    current = h1.iloc[-1]
    candle_id = str(int(current["open_time"]))

    long_bias = bias["close"] > bias["ema200"] and bias["ema20"] > bias["ema50"]
    short_bias = bias["close"] < bias["ema200"] and bias["ema20"] < bias["ema50"]
    long_alignment = current["ema20"] > current["ema50"] > current["ema200"]
    short_alignment = current["ema20"] < current["ema50"] < current["ema200"]

    prior = h1.iloc[-6:-1]
    bos_long = current["close"] > prior["high"].max()
    bos_short = current["close"] < prior["low"].min()

    sweep_long = False
    sweep_short = False
    sweep_low = float(current["low"])
    sweep_high = float(current["high"])
    start = len(h1) - 5
    for i in range(max(10, start), len(h1) - 1):
        prior10 = h1.iloc[i-10:i]
        candle = h1.iloc[i]
        if candle["low"] < prior10["low"].min() and candle["close"] > prior10["low"].min():
            sweep_long = True
            sweep_low = min(sweep_low, float(candle["low"]))
        if candle["high"] > prior10["high"].max() and candle["close"] < prior10["high"].max():
            sweep_short = True
            sweep_high = max(sweep_high, float(candle["high"]))

    volume_ok = current["volume"] >= 0.8 * current["vol_sma20"]
    atr = float(current["atr"])
    if atr <= 0:
        return candle_id, None

    direction = None
    if long_bias and long_alignment and sweep_long and bos_long and volume_ok:
        direction = "LONG"
        entry = float(current["close"])
        stop = sweep_low - 0.2 * atr
        target = entry + MIN_RR * (entry - stop)
    elif short_bias and short_alignment and sweep_short and bos_short and volume_ok:
        direction = "SHORT"
        entry = float(current["close"])
        stop = sweep_high + 0.2 * atr
        target = entry - MIN_RR * (stop - entry)
    else:
        return candle_id, None

    risk_distance = abs(entry - stop)
    if risk_distance <= 0 or abs(target - entry) / risk_distance < MIN_RR:
        return candle_id, None

    risk_amount = ACCOUNT_EQUITY * RISK_PCT if ACCOUNT_EQUITY > 0 else 0
    qty = risk_amount / risk_distance if risk_amount > 0 else 0
    notional = qty * entry if qty > 0 else 0
    candle_time = datetime.fromtimestamp(int(current["open_time"]) / 1000, tz=timezone.utc)
    return candle_id, {
        "symbol": symbol, "direction": direction, "entry": entry, "stop": stop, "target": target,
        "rr": MIN_RR, "risk_pct": RISK_PCT * 100, "risk_amount": risk_amount,
        "qty": qty, "notional": notional, "candle_time": candle_time.strftime("%Y-%m-%d %H:%M UTC"),
    }


def format_signal(signal: dict) -> str:
    side = "🟢 LONG" if signal["direction"] == "LONG" else "🔴 SHORT"
    lines = [
        "⚡ BGM TRADING SIGNALS", "", f"{side} | {signal['symbol']} (Binance USDⓈ-M)",
        f"Entrada de referencia: {signal['entry']:.6g}",
        f"Stop Loss: {signal['stop']:.6g}", f"Take Profit: {signal['target']:.6g}",
        f"Relación riesgo/beneficio: 1:{signal['rr']:.1f}",
        f"Riesgo por operación: {signal['risk_pct']:.2f}% de la cuenta",
    ]
    if signal["risk_amount"] > 0:
        lines += [f"Riesgo estimado: {signal['risk_amount']:.2f} USDT",
                  f"Tamaño estimado: {signal['qty']:.6g} {signal['symbol'].replace('USDT', '')}",
                  f"Notional aproximado: {signal['notional']:.2f} USDT"]
    lines += [
        f"Vela de confirmación: {signal['candle_time']}", "",
        "Filtros: tendencia H4 + EMA20/50/200 H1 + barrido de liquidez + ruptura estructural + volumen.",
        "⚠️ Señal informativa; no garantiza resultados. Verifica spread, comisiones y slippage. No es una orden automática."
    ]
    return "\n".join(lines)


def scan(send_message):
    state = load_state()
    for symbol in SYMBOLS:
        try:
            candle_id, signal = detect_signal(symbol)
            if candle_id is None:
                continue
            state_key = f"{symbol}_last_checked_h1"
            if state.get(state_key) == candle_id:
                continue
            state[state_key] = candle_id
            save_state(state)
            if signal:
                log.info("Señal %s %s", signal["direction"], symbol)
                send_message(format_signal(signal))
            else:
                log.info("NO TRADE: %s; no cumple todas las condiciones", symbol)
        except Exception as exc:
            log.exception("Error analizando %s: %s", symbol, exc)
