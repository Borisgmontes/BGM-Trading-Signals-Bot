"""Historical BTCUSDT OHLCV downloader from public Binance.US market data."""
from __future__ import annotations
import time
import requests
import pandas as pd

BASE_URL = "https://api.binance.us/api/v3/klines"
COLUMNS = ["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]

def fetch_btc_candles(timeframe: str = "5m", limit: int = 1000,
                      start_time_ms: int | None = None, end_time_ms: int | None = None,
                      pause_seconds: float = 0.15) -> pd.DataFrame:
    if timeframe not in {"1m","5m","15m","1h","4h","1d"}:
        raise ValueError("Unsupported BTC timeframe.")
    if not 250 <= limit <= 100000:
        raise ValueError("limit must be between 250 and 100000")
    session = requests.Session()
    rows = []
    if start_time_ms is None:
        # Fetch the most recent page, then walk backwards to obtain older history.
        params = {"symbol":"BTCUSDT","interval":timeframe,"limit":min(1000,limit)}
        if end_time_ms is not None:
            params["endTime"] = end_time_ms
        response = session.get(BASE_URL, params=params, timeout=20,
                               headers={"User-Agent":"BGM-Quant-Lab/0.1"})
        response.raise_for_status()
        batch = response.json()
        rows = list(batch)
        cursor_end = int(batch[0][0])-1 if batch else None
        while cursor_end is not None and len(rows) < limit:
            params = {"symbol":"BTCUSDT","interval":timeframe,
                      "limit":min(1000,limit-len(rows)),"endTime":cursor_end}
            response = session.get(BASE_URL,params=params,timeout=20,
                                   headers={"User-Agent":"BGM-Quant-Lab/0.1"})
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            rows = list(batch) + rows
            next_cursor = int(batch[0][0])-1
            if next_cursor >= cursor_end:
                break
            cursor_end = next_cursor
            if len(batch) < params["limit"]:
                break
            if pause_seconds:
                time.sleep(pause_seconds)
    else:
        cursor = start_time_ms
        while len(rows) < limit:
            params = {"symbol":"BTCUSDT","interval":timeframe,
                      "limit":min(1000,limit-len(rows)),"startTime":cursor}
            if end_time_ms is not None:
                params["endTime"] = end_time_ms
            response = session.get(BASE_URL,params=params,timeout=20,
                                   headers={"User-Agent":"BGM-Quant-Lab/0.1"})
            response.raise_for_status()
            batch = response.json()
            if not batch:
                break
            rows.extend(batch)
            next_cursor = int(batch[-1][0])+1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(batch) < params["limit"]:
                break
            if pause_seconds:
                time.sleep(pause_seconds)
    if len(rows) < 250:
        raise ValueError(f"Only {len(rows)} candles returned; at least 250 are required.")
    frame = pd.DataFrame(rows,columns=COLUMNS)
    for col in ("open","high","low","close","volume"):
        frame[col] = pd.to_numeric(frame[col],errors="coerce")
    frame["open_time"] = pd.to_datetime(frame["open_time"],unit="ms",utc=True)
    frame = (frame.dropna(subset=["open","high","low","close","volume"])
             .drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True))
    # Only drop the live candle for a latest-history request; keep fully historical ranges intact.
    if end_time_ms is None and len(frame) > 1:
        frame = frame.iloc[:-1].reset_index(drop=True)
    return frame
