"""Auditable strategy definitions and reproducible candidate generation."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
import hashlib, json, random, math, re

BASE_FEATURES = {
    "close", "volume_ratio", "macd_hist",
    "session_asia_open", "session_london_open", "session_new_york_open",
}
TIMEFRAMES = {"1m":60,"5m":300,"15m":900,"1h":3600,"4h":14400,"1d":86400}

def supported_feature(feature: str) -> bool:
    if feature in BASE_FEATURES: return True
    patterns = (
        r"ema_\\d+", r"rsi_\\d+", r"atr_\\d+",
        r"bb_(?:upper|lower)_\\d+", r"volume_ratio_\\d+",
        r"macd_hist_\\d+_\\d+_\\d+",
        r"ema_\\d+_cross_(?:up|down)_ema_\\d+",
    )
    return any(re.fullmatch(pattern, feature) for pattern in patterns)

@dataclass(frozen=True)
class Condition:
    feature: str
    operator: str
    value: float | str
    timeframe: str | None = None
    def __post_init__(self):
        if not supported_feature(self.feature): raise ValueError(f"Unsupported feature: {self.feature}")
        if self.operator not in {">", "<", ">=", "<="}: raise ValueError("Unsupported operator.")
        if isinstance(self.value, str) and not supported_feature(self.value): raise ValueError(f"Unsupported comparison feature: {self.value}")
        if not isinstance(self.value, (int, float, str)) or isinstance(self.value, bool):
            raise ValueError("Condition value must be a number or supported indicator name.")
        if isinstance(self.value, (int, float)) and not math.isfinite(float(self.value)):
            raise ValueError("Condition numeric values must be finite.")
        if self.timeframe is not None and self.timeframe not in TIMEFRAMES:
            raise ValueError(f"Unsupported condition timeframe: {self.timeframe}")

@dataclass(frozen=True)
class Strategy:
    name: str
    long_conditions: tuple[Condition, ...]
    short_conditions: tuple[Condition, ...]
    stop_atr: float = 1.8
    reward_risk: float = 2.0
    max_holding_bars: int = 48
    risk_per_trade_pct: float = 1.0
    long_exit_conditions: tuple[Condition, ...] = ()
    short_exit_conditions: tuple[Condition, ...] = ()
    indicator_settings: dict = field(default_factory=dict)
    def __post_init__(self):
        if not self.long_conditions or not self.short_conditions: raise ValueError("Both LONG and SHORT conditions are required.")
        if not 0.5 <= self.stop_atr <= 5: raise ValueError("stop_atr must be between 0.5 and 5.")
        if not 0.5 <= self.reward_risk <= 6: raise ValueError("reward_risk must be between 0.5 and 6.")
        if not 1 <= self.max_holding_bars <= 1000: raise ValueError("max_holding_bars must be between 1 and 1000.")
        if not 0.1 <= self.risk_per_trade_pct <= 5: raise ValueError("risk_per_trade_pct must be between 0.1 and 5.")
    @property
    def strategy_id(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
    def to_dict(self) -> dict:
        return {"name":self.name,"long_conditions":[asdict(x) for x in self.long_conditions],
                "short_conditions":[asdict(x) for x in self.short_conditions],"stop_atr":self.stop_atr,
                "reward_risk":self.reward_risk,"max_holding_bars":self.max_holding_bars,
                "risk_per_trade_pct":self.risk_per_trade_pct,
                "long_exit_conditions":[asdict(x) for x in self.long_exit_conditions],
                "short_exit_conditions":[asdict(x) for x in self.short_exit_conditions],
                "indicator_settings":self.indicator_settings}

def strategy_from_dict(payload: dict) -> Strategy:
    if not isinstance(payload, dict): raise ValueError("Strategy JSON root must be an object.")
    required={"name","long_conditions","short_conditions"}
    missing=required-payload.keys()
    if missing: raise ValueError(f"Missing strategy fields: {sorted(missing)}")
    def conditions(items):
        if not isinstance(items,list) or not items: raise ValueError("Each direction must contain at least one condition.")
        return tuple(Condition(**item) for item in items)
    exits=lambda key: tuple(Condition(**x) for x in payload.get(key,[]))
    settings=payload.get("indicator_settings",{})
    if not isinstance(settings,dict): raise ValueError("indicator_settings must be an object.")
    return Strategy(str(payload["name"]),conditions(payload["long_conditions"]),conditions(payload["short_conditions"]),
        float(payload.get("stop_atr",1.8)),float(payload.get("reward_risk",2.0)),
        int(payload.get("max_holding_bars",48)),float(payload.get("risk_per_trade_pct",1.0)),
        exits("long_exit_conditions"),exits("short_exit_conditions"),settings)

def generate_candidates(count: int, seed: int = 7) -> list[Strategy]:
    if count < 1 or count > 100_000: raise ValueError("count must be between 1 and 100000")
    rng=random.Random(seed)
    templates=[("rsi_14",[(">",50),(">",55),("<",50),("<",45)]),("volume_ratio",[(">",1.0),(">",1.2),(">",1.5)]),("macd_hist",[(">",0),("<",0)]),("close",[(">", "ema_200"),("<","ema_200")]),("ema_20",[(">", "ema_50"),("<","ema_50")]),("close",[(">", "bb_upper_20"),("<","bb_lower_20")])]
    found={}; attempts=0
    while len(found)<count and attempts<count*30:
        attempts+=1; chosen=rng.sample(templates,k=rng.randint(2,3)); longs=[]; shorts=[]
        for feature,options in chosen:
            op,value=rng.choice(options);longs.append(Condition(feature,op,value))
            shorts.append(Condition(feature,{ "<":">",">":"<","<=":">=",">=":"<="}[op],value))
        candidate=Strategy(f"BTC-{len(found)+1:04d}",tuple(longs),tuple(shorts),round(rng.uniform(1.2,2.8),2),rng.choice((1.5,2.0,2.5,3.0)),rng.choice((12,24,48,72)))
        found[candidate.strategy_id]=candidate
    return list(found.values())
