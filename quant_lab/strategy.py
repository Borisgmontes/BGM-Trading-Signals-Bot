"""Auditable strategy definitions and reproducible candidate generation."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib, json, random
ALLOWED_FEATURES = {"close", "ema_10", "ema_20", "ema_50", "ema_100", "ema_200", "rsi_14", "atr_14", "bb_upper", "bb_lower", "volume_ratio", "macd_hist"}
@dataclass(frozen=True)
class Condition:
    feature: str
    operator: str
    value: float | str
    def __post_init__(self):
        if self.feature not in ALLOWED_FEATURES: raise ValueError(f"Unsupported feature: {self.feature}")
        if self.operator not in {">", "<", ">=", "<="}: raise ValueError(f"Unsupported operator: {self.operator}")
        if isinstance(self.value, str) and self.value not in ALLOWED_FEATURES: raise ValueError(f"Unsupported comparison feature: {self.value}")
@dataclass(frozen=True)
class Strategy:
    name: str
    long_conditions: tuple[Condition, ...]
    short_conditions: tuple[Condition, ...]
    stop_atr: float = 1.8
    reward_risk: float = 2.0
    max_holding_bars: int = 48
    def __post_init__(self):
        if not self.long_conditions or not self.short_conditions: raise ValueError("Both LONG and SHORT conditions are required.")
        if not 0.5 <= self.stop_atr <= 5: raise ValueError("stop_atr must be between 0.5 and 5.")
        if not 0.5 <= self.reward_risk <= 6: raise ValueError("reward_risk must be between 0.5 and 6.")
        if not 1 <= self.max_holding_bars <= 1000: raise ValueError("max_holding_bars must be between 1 and 1000.")
    @property
    def strategy_id(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]
    def to_dict(self) -> dict:
        return {"name": self.name, "long_conditions": [asdict(x) for x in self.long_conditions], "short_conditions": [asdict(x) for x in self.short_conditions], "stop_atr": self.stop_atr, "reward_risk": self.reward_risk, "max_holding_bars": self.max_holding_bars}
def generate_candidates(count: int, seed: int = 7) -> list[Strategy]:
    if count < 1 or count > 100_000: raise ValueError("count must be between 1 and 100000")
    rng = random.Random(seed)
    templates = [("rsi_14", [(">",50),(">",55),("<",50),("<",45)]), ("volume_ratio", [(">",1.0),(">",1.2),(">",1.5)]), ("macd_hist", [(">",0),("<",0)]), ("close", [(">", "ema_200"),("<","ema_200")]), ("ema_20", [(">", "ema_50"),("<","ema_50")]), ("close", [(">", "bb_upper"),("<","bb_lower")])]
    found = {}
    attempts = 0
    while len(found) < count and attempts < count*30:
        attempts += 1
        chosen = rng.sample(templates, k=rng.randint(2,3)); longs=[]; shorts=[]
        for feature, options in chosen:
            op, value = rng.choice(options); longs.append(Condition(feature,op,value))
            inverse = {"<":">",">":"<","<=":">=",">=":"<="}[op]
            shorts.append(Condition(feature,inverse,value))
        candidate = Strategy(f"BTC-{len(found)+1:04d}", tuple(longs), tuple(shorts), round(rng.uniform(1.2,2.8),2), rng.choice((1.5,2.0,2.5,3.0)), rng.choice((12,24,48,72)))
        found[candidate.strategy_id] = candidate
    return list(found.values())
