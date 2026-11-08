"""CLI for the first BGM Quant Lab BTC research workflow."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from .data import fetch_btc_candles
from .indicators import add_indicators
from .strategy import generate_candidates, strategy_from_dict
from .validation import train_test_report,monte_carlo_trade_bootstrap
from .ranking import score_candidate

def main():
    parser=argparse.ArgumentParser(description="BGM Quant Lab BTC research MVP")
    parser.add_argument("--timeframe",default=None,choices=["1m","5m","15m","1h","4h","1d"])
    parser.add_argument("--candles",type=int,default=5000)
    parser.add_argument("--candidates",type=int,default=100)
    parser.add_argument("--seed",type=int,default=7)
    parser.add_argument("--strategy-json",help="Run one user strategy exported by the dashboard")
    parser.add_argument("--fee-bps",type=float,default=5.0,help="Trading fee in basis points per side")
    parser.add_argument("--slippage-bps",type=float,default=2.0,help="Slippage assumption in basis points per side")
    parser.add_argument("--initial-equity",type=float,default=10000.0,help="Starting capital in quote currency")
    parser.add_argument("--output",default="quant_lab/results")
    args=parser.parse_args()
    payload=None
    if args.strategy_json:
        payload=json.loads(Path(args.strategy_json).read_text(encoding="utf-8"))
        candidates=[strategy_from_dict(payload.get("strategy", payload))]
    else:
        candidates=generate_candidates(args.candidates,args.seed)
    timeframe=args.timeframe or (payload.get("timeframe","5m") if isinstance(payload,dict) else "5m")
    data=add_indicators(fetch_btc_candles(timeframe,args.candles))
    results=[]
    for strategy in candidates:
        try:
            report=train_test_report(data,strategy,fee_bps=args.fee_bps,
                                     slippage_bps=args.slippage_bps,
                                     initial_equity=args.initial_equity)
            test=report["out_of_sample"]
            quality=score_candidate(report)
            results.append({"strategy":strategy.to_dict(),"strategy_id":strategy.strategy_id,
                "validation":report,"quality":quality,
                "monte_carlo":monte_carlo_trade_bootstrap(test["trade_returns_pct"])
                if len(test["trade_returns_pct"]) >= 30 else None})
        except ValueError as exc:
            results.append({"strategy_id":strategy.strategy_id,"error":str(exc)})
    results.sort(key=lambda x:x.get("quality",{}).get("research_score",0),reverse=True)
    output=Path(args.output); output.mkdir(parents=True,exist_ok=True)
    target=output/"btc_candidates.json"
    target.write_text(json.dumps({"market":"BTCUSDT","timeframe":timeframe,
        "candles":len(data),"costs":{"fee_bps_per_side":args.fee_bps,
        "slippage_bps_per_side":args.slippage_bps},"initial_equity":args.initial_equity,
        "candidates":results},indent=2,allow_nan=False),encoding="utf-8")
    print(f"Processed {len(candidates)} candidates. Report: {target}")
    print("Research only: no orders are sent and profitability is not guaranteed.")

if __name__=="__main__":
    main()
