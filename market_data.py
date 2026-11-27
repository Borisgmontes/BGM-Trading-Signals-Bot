"""Multi-asset OHLCV adapter for BGM Radar.

Crypto uses Binance.US spot candles. Gold and FX use Yahoo Finance chart
history as a development proxy, NOT Weltrade Bid/Ask or broker-executable
prices. A production-grade Weltrade backtest still requires MT5-exported
Bid/Ask history (or an approved broker feed).
"""
import time
import requests
import pandas as pd

BINANCE_URL = "https://api.binance.us/api/v3/klines"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
CRYPTO_SYMBOLS = {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT"}
YAHOO_SYMBOLS = {
    "XAUUSD": "GC=F",       # Gold futures proxy, not Weltrade spot
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "CAD=X",
    "USDCHF": "CHF=X",
}
SYMBOLS = CRYPTO_SYMBOLS | set(YAHOO_SYMBOLS)
INTERVALS = {"5m": "5m", "15m": "15m", "1h": "60m", "4h": "60m"}


def fetch_market_candles(symbol, timeframe, limit=1000):
    symbol = str(symbol).upper()
    if symbol not in SYMBOLS:
        raise ValueError(f"Instrumento no habilitado: {symbol}")
    if timeframe not in INTERVALS:
        raise ValueError(f"Temporalidad no soportada: {timeframe}")
    if symbol in CRYPTO_SYMBOLS:
        response = requests.get(
            BINANCE_URL,
            params={"symbol": symbol, "interval": timeframe, "limit": min(int(limit), 1000)},
            headers={"User-Agent": "BGM-Radar/3.0"},
            timeout=20,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list) or len(rows) < 220:
            raise ValueError(f"Datos insuficientes para {symbol} {timeframe}")
        cols = ["open_time", "open", "high", "low", "close", "volume", "close_time",
                "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
        frame = pd.DataFrame(rows, columns=cols)
        frame = frame[["open_time", "open", "high", "low", "close", "volume", "close_time"]]
        for col in frame.columns:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        return frame.dropna().iloc[:-1].reset_index(drop=True)

    ticker = YAHOO_SYMBOLS[symbol]
    interval = INTERVALS[timeframe]
    params = {"interval": interval, "range": "60d" if interval in ("5m", "15m") else "2y",
              "events": "history"}
    response = requests.get(YAHOO_URL.format(ticker=ticker), params=params,
                            headers={"User-Agent": "Mozilla/5.0 BGM-Radar/3.0"}, timeout=20)
    response.raise_for_status()
    payload = response.json().get("chart", {})
    if payload.get("error") or not payload.get("result"):
        raise ValueError(f"Proveedor histórico no devolvió datos para {symbol}")
    result = payload["result"][0]
    quote = result.get("indicators", {}).get("quote", [{}])[0]
    timestamps = result.get("timestamp") or []
    frame = pd.DataFrame({
        "open_time": [int(x * 1000) for x in timestamps],
        "open": quote.get("open", []), "high": quote.get("high", []),
        "low": quote.get("low", []), "close": quote.get("close", []),
        "volume": quote.get("volume", []),
    }).dropna(subset=["open", "high", "low", "close"])
    if frame.empty:
        raise ValueError(f"Histórico vacío para {symbol}")
    frame["open_time"] = pd.to_numeric(frame["open_time"])
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["volume"] = frame["volume"].fillna(0)
    if timeframe == "4h":
        frame.index = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
        frame = frame.resample("4h").agg({
            "open_time": "first", "open": "first", "high": "max",
            "low": "min", "close": "last", "volume": "sum"
        }).dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    frame["close_time"] = frame["open_time"] + ({"5m": 300000, "15m": 900000,
                                                   "1h": 3600000, "4h": 14400000}[timeframe]) - 1
    # Exclude the currently forming candle.
    duration = {"5m": 300000, "15m": 900000, "1h": 3600000, "4h": 14400000}[timeframe]
    now_ms = int(time.time() * 1000)
    frame = frame[frame["open_time"] + duration <= now_ms]
    return frame.tail(limit).reset_index(drop=True)
