"""Multi-asset market data, causal indicators and risk-based OHLC backtesting."""
from __future__ import annotations
import math
from typing import Any
import pandas as pd
import yfinance as yf

MARKETS = {
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum", "SOL-USD": "Solana",
    "BNB-USD": "BNB", "XRP-USD": "XRP", "ADA-USD": "Cardano",
    "SPY": "S&P 500 ETF", "QQQ": "Nasdaq 100 ETF", "DIA": "Dow Jones ETF",
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA",
    "TSLA": "Tesla", "AMZN": "Amazon", "GOOGL": "Alphabet",
    "GC=F": "Gold Futures", "SI=F": "Silver Futures",
    "CL=F": "Crude Oil Futures", "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD", "JPY=X": "USD/JPY"
}
INTERVALS = {"5m": "5m", "15m": "15m", "1h": "60m", "4h": "60m", "1d": "1d"}

def fetch_market_data(symbol: str, timeframe: str = "1h", candles: int = 1500) -> pd.DataFrame:
    if symbol not in MARKETS:
        raise ValueError("Activo no soportado. Selecciona un símbolo del catálogo.")
    if timeframe not in INTERVALS:
        raise ValueError("Temporalidad no soportada.")
    if not 300 <= int(candles) <= 10000:
        raise ValueError("Solicita entre 300 y 10000 velas.")
    interval = INTERVALS[timeframe]
    if interval in ("5m", "15m"):
        period = "60d"
    elif interval == "60m":
        period = "730d"
    else:
        period = "max"
    try:
        raw = yf.download(symbol, period=period, interval=interval, auto_adjust=True,
                          progress=False, threads=False, timeout=25)
        if raw is None or raw.empty:
            raise RuntimeError("Yahoo Finance no devolvió velas.")
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        raw = raw.rename(columns={str(c).lower(): str(c).lower() for c in raw.columns})
        needed = ["open", "high", "low", "close", "volume"]
        if any(c not in raw.columns for c in needed):
            raise RuntimeError("El proveedor no devolvió OHLCV completo.")
        frame = raw[needed].copy().dropna(subset=["open", "high", "low", "close"])
        frame["volume"] = frame["volume"].fillna(0.0)
        if timeframe == "4h":
            frame = frame.resample("4h").agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum"}).dropna()
        frame = frame.tail(candles).reset_index()
        time_col = "Datetime" if "Datetime" in frame.columns else "Date"
        frame = frame.rename(columns={time_col:"open_time"})
        frame["open_time"] = pd.to_datetime(frame["open_time"], utc=True)
        for col in needed:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=needed).reset_index(drop=True)
        if len(frame) < 250:
            raise RuntimeError(f"Solo se recibieron {len(frame)} velas cerradas; se necesitan al menos 250. Prueba 1h o 1d.")
        # Exclude the current, potentially incomplete candle.
        if len(frame) > 1:
            frame = frame.iloc[:-1].reset_index(drop=True)
        return frame
    except Exception as exc:
        raise RuntimeError(f"No se pudieron descargar datos de {symbol} ({timeframe}): {exc}") from exc

def add_market_indicators(df: pd.DataFrame, fast: int = 20, slow: int = 50, trend: int = 200) -> pd.DataFrame:
    if not (2 <= fast < slow < trend <= 500):
        raise ValueError("EMAs deben cumplir 2 ≤ rápida < lenta < tendencia ≤ 500.")
    out = df.copy()
    close = out["close"].astype(float)
    for period in sorted(set([fast, slow, trend, 20, 50, 200])):
        out[f"ema_{period}"] = close.ewm(span=period, adjust=False, min_periods=period).mean()
    typical = (out["high"] + out["low"] + close) / 3
    volume = out["volume"].astype(float)
    # Cumulative VWAP is causal; reset by UTC calendar day for intraday charts.
    day = pd.to_datetime(out["open_time"], utc=True).dt.floor("D")
    pv = typical * volume
    out["vwap"] = pv.groupby(day).cumsum() / volume.groupby(day).cumsum().replace(0, float("nan"))
    prev = close.shift(1)
    tr = pd.concat([out["high"]-out["low"], (out["high"]-prev).abs(), (out["low"]-prev).abs()], axis=1).max(axis=1)
    out["atr_14"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    return out.replace([float("inf"), float("-inf")], float("nan"))

def run_market_backtest(df: pd.DataFrame, config: dict[str, Any]) -> dict[str, Any]:
    initial = float(config.get("initial_equity", 10000))
    risk_pct = float(config.get("risk_per_trade_pct", 1))
    stop_mult = float(config.get("stop_atr", 1.8))
    rr = float(config.get("reward_risk", 2))
    fee = float(config.get("fee_bps", 5))/10000
    slip = float(config.get("slippage_bps", 2))/10000
    max_bars = int(config.get("max_holding_bars", 48))
    fast, slow, trend = (int(config.get(k, d)) for k,d in (("ema_fast",20),("ema_slow",50),("ema_trend",200)))
    use_vwap = bool(config.get("use_vwap", True))
    allow_short = bool(config.get("allow_short", True))
    if not all(math.isfinite(x) for x in [initial,risk_pct,stop_mult,rr,fee,slip]) or initial <= 0 or not .1 <= risk_pct <= 5 or not .5 <= stop_mult <= 5 or not .5 <= rr <= 6 or fee < 0 or slip < 0 or not 1 <= max_bars <= 1000:
        raise ValueError("Configuración de capital, riesgo, costes o SL/TP fuera de rango.")
    data = add_market_indicators(df, fast, slow, trend)
    equity = initial
    curve = [initial]
    trades = []
    i = max(trend, 200)
    while i < len(data)-1:
        row = data.iloc[i]
        prev = data.iloc[i-1]
        vals = [row.get(f"ema_{fast}"), row.get(f"ema_{slow}"), row.get(f"ema_{trend}"), row.get("atr_14")]
        if any(pd.isna(x) for x in vals):
            i += 1
            continue
        # Trend alignment plus a fresh fast/slow EMA crossover; VWAP is an optional confirmation.
        cross_up = prev[f"ema_{fast}"] <= prev[f"ema_{slow}"] and row[f"ema_{fast}"] > row[f"ema_{slow}"]
        cross_dn = prev[f"ema_{fast}"] >= prev[f"ema_{slow}"] and row[f"ema_{fast}"] < row[f"ema_{slow}"]
        vwap_long = (not use_vwap) or (pd.notna(row["vwap"]) and row["close"] > row["vwap"])
        vwap_short = (not use_vwap) or (pd.notna(row["vwap"]) and row["close"] < row["vwap"])
        long_sig = cross_up and row["close"] > row[f"ema_{trend}"] and vwap_long
        short_sig = allow_short and cross_dn and row["close"] < row[f"ema_{trend}"] and vwap_short
        direction = 1 if long_sig else (-1 if short_sig else 0)
        if direction == 0:
            i += 1
            continue
        entry_i = i+1
        entry = float(data.iloc[entry_i]["open"]) * (1 + slip if direction == 1 else 1 - slip)
        distance = float(row["atr_14"]) * stop_mult
        if entry <= 0 or distance <= 0 or not math.isfinite(distance):
            i += 1
            continue
        stop = entry - direction*distance
        target = entry + direction*distance*rr
        end_i = min(len(data)-1, entry_i+max_bars-1)
        exit_i, exit_price, reason = end_i, float(data.iloc[end_i]["close"]), "TIME"
        for j in range(entry_i, end_i+1):
            high, low = float(data.iloc[j]["high"]), float(data.iloc[j]["low"])
            hit_sl = low <= stop if direction == 1 else high >= stop
            hit_tp = high >= target if direction == 1 else low <= target
            if hit_sl:
                exit_i, exit_price, reason = j, stop, "SL"
                break
            if hit_tp:
                exit_i, exit_price, reason = j, target, "TP"
                break
        exit_price *= (1 - slip if direction == 1 else 1 + slip)
        risk_cash = equity*risk_pct/100
        quantity = risk_cash/distance
        notional = quantity*entry
        # Cap unleveraged exposure at account equity; short notional uses the same conservative cap.
        quantity = min(quantity, equity/entry)
        gross = direction*(exit_price-entry)*quantity
        costs = (entry+exit_price)*quantity*(fee+slip)
        pnl = gross-costs
        before = equity
        equity = max(0.0, equity+pnl)
        ret = pnl/before*100 if before else 0.0
        trades.append({"side":"LONG" if direction==1 else "SHORT","entry_time":data.iloc[entry_i]["open_time"].isoformat(),"exit_time":data.iloc[exit_i]["open_time"].isoformat(),"entry_price":entry,"exit_price":exit_price,"stop_loss":stop,"take_profit":target,"exit_reason":reason,"quantity":quantity,"pnl":pnl,"return_pct":ret,"equity_after":equity})
        curve.append(equity)
        i = exit_i+1
    wins = [t["pnl"] for t in trades if t["pnl"] > 0]
    losses = [t["pnl"] for t in trades if t["pnl"] < 0]
    gross_profit, gross_loss = sum(wins), abs(sum(losses))
    peak, dd = initial, 0.0
    for value in curve:
        peak = max(peak,value)
        if peak:
            dd = max(dd,(peak-value)/peak*100)
    final = equity
    return {"initial_equity":initial,"final_equity":final,"net_profit":final-initial,"trades":len(trades),
            "wins":len(wins),"losses":len(losses),"win_rate_pct":len(wins)/len(trades)*100 if trades else 0.0,
            "profit_factor":gross_profit/gross_loss if gross_loss else (None if gross_profit else 0.0),
            "max_drawdown_pct":dd,"net_return_pct":(final/initial-1)*100,
            "equity_curve":curve,"trade_log":trades,
            "candles":data.tail(1500).replace({float("nan"):None}).to_dict(orient="records")}
