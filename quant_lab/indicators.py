"""Causal indicators with user-configurable periods."""
from __future__ import annotations
import pandas as pd

DEFAULTS = {"ema_periods":[10,20,50,100,200],"rsi_period":14,"atr_period":14,
            "bb_period":20,"bb_std":2.0,"macd_fast":12,"macd_slow":26,
            "macd_signal":9,"volume_period":20,"cross_pairs":[[10,20],[20,50],[50,200]]}

def normalize_indicator_settings(settings=None):
    cfg={**DEFAULTS,**(settings or {})}
    def periods(key, low=2, high=500, maximum=20):
        values=cfg[key]
        if not isinstance(values,list) or not values or len(values)>maximum:
            raise ValueError(f"{key} must be a list with 1 to {maximum} periods.")
        result=sorted(set(int(x) for x in values))
        if any(x<low or x>high for x in result): raise ValueError(f"{key} periods must be between {low} and {high}.")
        return result
    cfg["ema_periods"]=periods("ema_periods")
    for key in ("rsi_period","atr_period","bb_period","volume_period","macd_fast","macd_slow","macd_signal"):
        cfg[key]=int(cfg[key])
        if not 2<=cfg[key]<=500: raise ValueError(f"{key} must be between 2 and 500.")
    cfg["bb_std"]=float(cfg["bb_std"])
    if not 0.1<=cfg["bb_std"]<=5: raise ValueError("bb_std must be between 0.1 and 5.")
    if cfg["macd_fast"]>=cfg["macd_slow"]: raise ValueError("macd_fast must be smaller than macd_slow.")
    pairs=cfg["cross_pairs"]
    if not isinstance(pairs,list) or len(pairs)>30: raise ValueError("cross_pairs must contain at most 30 EMA pairs.")
    normalized=[]
    for pair in pairs:
        if not isinstance(pair,(list,tuple)) or len(pair)!=2: raise ValueError("Each cross pair must contain two EMA periods.")
        fast,slow=map(int,pair)
        if not 2<=fast<slow<=500: raise ValueError("EMA cross pairs require 2 <= fast < slow <= 500.")
        normalized.append([fast,slow])
    cfg["cross_pairs"]=normalized
    return cfg

def add_indicators(frame: pd.DataFrame, settings=None) -> pd.DataFrame:
    required={"open","high","low","close","volume"}
    missing=required.difference(frame.columns)
    if missing: raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")
    cfg=normalize_indicator_settings(settings)
    df=frame.copy();close=df["close"].astype(float)
    ema_periods=set(cfg["ema_periods"])
    ema_periods.update(x for pair in cfg["cross_pairs"] for x in pair)
    for period in sorted(ema_periods):
        df[f"ema_{period}"]=close.ewm(span=period,adjust=False).mean()
    # Preserve classic defaults for strategies saved before custom periods existed.
    for period in (10,20,50,100,200):
        if f"ema_{period}" not in df: df[f"ema_{period}"]=close.ewm(span=period,adjust=False).mean()
    rp=cfg["rsi_period"];delta=close.diff()
    gain=delta.clip(lower=0).ewm(alpha=1/rp,adjust=False,min_periods=rp).mean()
    loss=(-delta.clip(upper=0)).ewm(alpha=1/rp,adjust=False,min_periods=rp).mean()
    rs=gain/loss.replace(0,float("nan"))
    df[f"rsi_{rp}"]=(100-100/(1+rs)).mask((loss==0)&(gain>0),100)
    if rp==14: df["rsi_14"]=df[f"rsi_{rp}"]
    ap=cfg["atr_period"];prev=close.shift(1)
    tr=pd.concat([(df["high"]-df["low"]),(df["high"]-prev).abs(),(df["low"]-prev).abs()],axis=1).max(axis=1)
    df[f"atr_{ap}"]=tr.ewm(alpha=1/ap,adjust=False,min_periods=ap).mean()
    if ap==14: df["atr_14"]=df[f"atr_{ap}"]
    bp=cfg["bb_period"];mid=close.rolling(bp,min_periods=bp).mean();std=close.rolling(bp,min_periods=bp).std(ddof=0)
    df[f"bb_upper_{bp}"]=mid+cfg["bb_std"]*std;df[f"bb_lower_{bp}"]=mid-cfg["bb_std"]*std
    if bp==20:
        df["bb_upper"]=df[f"bb_upper_{bp}"];df["bb_lower"]=df[f"bb_lower_{bp}"]
    vp=cfg["volume_period"];df[f"volume_sma_{vp}"]=df["volume"].rolling(vp,min_periods=vp).mean()
    df[f"volume_ratio_{vp}"]=df["volume"]/df[f"volume_sma_{vp}"].replace(0,float("nan"))
    df["volume_ratio"]=df[f"volume_ratio_{vp}"]
    mf,ms,signal=cfg["macd_fast"],cfg["macd_slow"],cfg["macd_signal"]
    macd=close.ewm(span=mf,adjust=False).mean()-close.ewm(span=ms,adjust=False).mean()
    df[f"macd_hist_{mf}_{ms}_{signal}"]=macd-macd.ewm(span=signal,adjust=False).mean()
    df["macd_hist"]=df[f"macd_hist_{mf}_{ms}_{signal}"]
    for fast_period,slow_period in cfg["cross_pairs"]:
        fast_line,slow_line=df[f"ema_{fast_period}"],df[f"ema_{slow_period}"]
        df[f"ema_{fast_period}_cross_up_ema_{slow_period}"]=((fast_line.shift(1)<=slow_line.shift(1))&(fast_line>slow_line)).astype(float)
        df[f"ema_{fast_period}_cross_down_ema_{slow_period}"]=((fast_line.shift(1)>=slow_line.shift(1))&(fast_line<slow_line)).astype(float)
    if "open_time" in df.columns:
        utc_times=pd.to_datetime(df["open_time"],utc=True)
        for label,zone,opening in (("asia","Asia/Tokyo","09:00"),("london","Europe/London","08:00"),("new_york","America/New_York","09:30")):
            local=utc_times.dt.tz_convert(zone);hour,minute=map(int,opening.split(":"))
            df[f"session_{label}_open"]=((local.dt.hour==hour)&(local.dt.minute==minute)).astype(float)
    else:
        for label in ("asia","london","new_york"): df[f"session_{label}_open"]=0.0
    return df.replace([float("inf"),float("-inf")],float("nan"))
