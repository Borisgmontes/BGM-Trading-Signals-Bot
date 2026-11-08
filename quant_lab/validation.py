"""Out-of-sample, walk-forward and bootstrap trade-sequence checks."""
from __future__ import annotations
import random
import pandas as pd
from .backtest import run_backtest
from .strategy import Strategy

def train_test_report(df: pd.DataFrame, strategy: Strategy, train_fraction: float=0.70,
                      fee_bps: float=5.0, slippage_bps: float=2.0) -> dict:
    if not 0.5 <= train_fraction <= 0.9:
        raise ValueError("train_fraction must be between 0.5 and 0.9")
    split = int(len(df)*train_fraction)
    if split < 250 or len(df)-split < 50:
        raise ValueError("Not enough candles for train and out-of-sample partitions.")
    train = run_backtest(df.iloc[:split].reset_index(drop=True),strategy,fee_bps,slippage_bps)
    # 200 preceding candles warm indicators; backtest's first eligible signal is exactly at split.
    warmup = max(0,split-200)
    test_frame = df.iloc[warmup:].reset_index(drop=True)
    test = run_backtest(test_frame,strategy,fee_bps,slippage_bps)
    return {"train":train.to_dict(),"out_of_sample":test.to_dict(),
            "split_index":split,"out_of_sample_start":str(df.index[split])}

def walk_forward_report(df: pd.DataFrame, strategy: Strategy, windows: int=4,
                        fee_bps: float=5.0, slippage_bps: float=2.0) -> list[dict]:
    if windows < 2 or len(df) < windows*300:
        raise ValueError("Walk-forward requires at least 300 candles per window.")
    reports = []
    width = len(df)//windows
    for n in range(windows):
        start,end = n*width,(len(df) if n==windows-1 else (n+1)*width)
        segment = df.iloc[start:end].reset_index(drop=True)
        if len(segment) < 250:
            continue
        result = run_backtest(segment,strategy,fee_bps,slippage_bps)
        reports.append({"window":n+1,"start":str(df.index[start]),
                        "end":str(df.index[end-1]),"result":result.to_dict()})
    return reports

def monte_carlo_trade_bootstrap(trade_returns_pct: list[float], simulations: int=1000,
                                seed: int=19) -> dict:
    """Resample observed trades; tests sequence risk, not future market behaviour."""
    if not trade_returns_pct:
        raise ValueError("At least one completed trade is required.")
    if simulations < 100 or simulations > 100000:
        raise ValueError("simulations must be between 100 and 100000")
    rng = random.Random(seed)
    terminal,drawdowns = [],[]
    for _ in range(simulations):
        equity = peak = 1.0
        max_dd = 0.0
        for value in (rng.choice(trade_returns_pct) for _ in trade_returns_pct):
            equity *= max(0.0,1.0+value/100)
            peak = max(peak,equity)
            max_dd = max(max_dd,(peak-equity)/peak if peak else 0.0)
        terminal.append(equity)
        drawdowns.append(max_dd*100)
    terminal.sort()
    drawdowns.sort()
    return {"simulations":simulations,
            "terminal_equity_p05":terminal[int(.05*(simulations-1))],
            "terminal_equity_median":terminal[simulations//2],
            "max_drawdown_p95_pct":drawdowns[int(.95*(simulations-1))],
            "method":"bootstrap_with_replacement_of_observed_trades"}
