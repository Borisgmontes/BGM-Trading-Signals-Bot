"""Conservative OHLC backtester: signal at close, entry next bar open."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import math
import pandas as pd
from .strategy import Condition, Strategy

@dataclass
class BacktestResult:
    strategy_id: str
    trades: int
    win_rate_pct: float
    profit_factor: float | None
    expectancy_pct: float
    net_return_pct: float
    max_drawdown_pct: float
    average_trade_pct: float
    equity_curve: list[float]
    trade_returns_pct: list[float]
    def to_dict(self):
        return asdict(self)

def _condition_mask(df: pd.DataFrame, conditions: tuple[Condition,...]) -> pd.Series:
    mask = pd.Series(True,index=df.index)
    for rule in conditions:
        left = df[rule.feature]
        right = df[rule.value] if isinstance(rule.value,str) else rule.value
        if rule.operator == ">": current = left > right
        elif rule.operator == "<": current = left < right
        elif rule.operator == ">=": current = left >= right
        else: current = left <= right
        mask &= current.fillna(False)
    return mask

def run_backtest(df: pd.DataFrame, strategy: Strategy, fee_bps: float=5.0,
                 slippage_bps: float=2.0, initial_equity: float=10000.0) -> BacktestResult:
    if len(df) < 250:
        raise ValueError("At least 250 candles are required for a meaningful BTC test.")
    if not all(math.isfinite(float(x)) for x in (fee_bps, slippage_bps, initial_equity)) or fee_bps < 0 or slippage_bps < 0 or fee_bps > 100 or slippage_bps > 100 or initial_equity <= 0:
        raise ValueError("Fees/slippage must be finite and between 0 and 100 bps; initial equity must be positive.")
    required = {"open","high","low","close","atr_14"}
    if not required.issubset(df.columns):
        raise ValueError(f"Data must include indicators: {sorted(required)}")
    long_signal = _condition_mask(df,strategy.long_conditions)
    short_signal = _condition_mask(df,strategy.short_conditions)
    cost = 2*(fee_bps+slippage_bps)/10000
    equity = initial_equity
    curve = [equity]
    returns = []
    i = 200
    while i < len(df)-1:
        direction = 1 if bool(long_signal.iloc[i]) and not bool(short_signal.iloc[i]) else (
            -1 if bool(short_signal.iloc[i]) and not bool(long_signal.iloc[i]) else 0)
        if direction == 0 or not math.isfinite(float(df["atr_14"].iloc[i])):
            i += 1
            continue
        entry_i = i+1
        entry = float(df["open"].iloc[entry_i])
        distance = float(df["atr_14"].iloc[i])*strategy.stop_atr
        if entry <= 0 or distance <= 0 or not math.isfinite(distance):
            i += 1
            continue
        stop = entry-direction*distance
        target = entry+direction*distance*strategy.reward_risk
        last_i = min(len(df)-1,entry_i+strategy.max_holding_bars-1)
        exit_price = float(df["close"].iloc[last_i])
        exit_i = last_i
        for j in range(entry_i,last_i+1):
            high,low = float(df["high"].iloc[j]),float(df["low"].iloc[j])
            stop_hit = low <= stop if direction == 1 else high >= stop
            target_hit = high >= target if direction == 1 else low <= target
            # Conservative: assume the adverse stop happened first if both levels touch in one candle.
            if stop_hit:
                exit_price,exit_i = stop,j
                break
            if target_hit:
                exit_price,exit_i = target,j
                break
        # Unleveraged spot sizing: cap notional at 100% of equity and target max risk.
        stop_fraction = distance/entry
        position_fraction = min(1.0, (strategy.risk_per_trade_pct/100)/stop_fraction)
        net = position_fraction*(direction*(exit_price-entry)/entry-cost)
        equity *= max(0.0,1.0+net)
        returns.append(net*100)
        curve.append(equity)
        i = exit_i+1
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]
    gross_profit,gross_loss = sum(wins),abs(sum(losses))
    peak,max_dd = initial_equity,0.0
    for value in curve:
        peak = max(peak,value)
        if peak:
            max_dd = max(max_dd,(peak-value)/peak*100)
    avg = sum(returns)/len(returns) if returns else 0.0
    profit_factor = gross_profit/gross_loss if gross_loss else (None if gross_profit else 0.0)
    return BacktestResult(strategy.strategy_id,len(returns),
        len(wins)/len(returns)*100 if returns else 0.0,profit_factor,avg,
        (equity/initial_equity-1)*100,max_dd,avg,curve,returns)
