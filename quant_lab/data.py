"""Historical BTCUSDT OHLCV downloader from public Binance.US market data."""
from __future__ import annotations
import time, requests, pandas as pd
BASE_URL="https://api.binance.us/api/v3/klines"
COLUMNS=["open_time","open","high","low","close","volume","close_time","quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"]
def fetch_btc_candles(timeframe: str="5m",limit: int=1000,start_time_ms: int|None=None,end_time_ms: int|None=None,pause_seconds: float=.15) -> pd.DataFrame:
    if timeframe not in {"1m","5m","15m","1h","4h","1d"}: raise ValueError("Unsupported BTC timeframe.")
    if not 250<=limit<=100000: raise ValueError("limit must be between 250 and 100000")
    rows=[]; cursor=start_time_ms; session=requests.Session()
    while len(rows)<limit:
        params={"symbol":"BTCUSDT","interval":timeframe,"limit":min(1000,limit-len(rows))}
        if cursor is not None: params["startTime"]=cursor
        if end_time_ms is not None: params["endTime"]=end_time_ms
        response=session.get(BASE_URL,params=params,timeout=20,headers={"User-Agent":"BGM-Quant-Lab/0.1"}); response.raise_for_status(); batch=response.json()
        if not batch: break
        rows.extend(batch); next_cursor=int(batch[-1][0])+1
        if cursor is not None and next_cursor<=cursor: break
        cursor=next_cursor
        if len(batch)<params["limit"]: break
        if pause_seconds: time.sleep(pause_seconds)
    if len(rows)<250: raise ValueError(f"Only {len(rows)} candles returned; at least 250 are required.")
    frame=pd.DataFrame(rows[:limit],columns=COLUMNS)
    for col in ("open","high","low","close","volume"): frame[col]=pd.to_numeric(frame[col],errors="coerce")
    frame["open_time"]=pd.to_datetime(frame["open_time"],unit="ms",utc=True)
    frame=frame.dropna(subset=["open","high","low","close","volume"]).drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    # Drop the latest candle because it may still be forming.
    if len(frame)>1: frame=frame.iloc[:-1].reset_index(drop=True)
    return frame
