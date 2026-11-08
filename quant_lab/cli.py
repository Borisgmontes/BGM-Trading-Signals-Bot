"""CLI for the first BGM Quant Lab BTC research workflow."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from .data import fetch_btc_candles
from .indicators import add_indicators
from .strategy import generate_candidates, strategy_from_dict
from .validation import train_test_report,monte_carlo_trade_bootstrap
from .ranking import score_candidate

def resolve_options(args, payload=None):
    """Resolve CLI overrides against dashboard-exported JSON defaults."""
    payload = payload or {}
    return {
        "timeframe": args.timeframe or payload.get("timeframe", "5m"),
        "candles": args.candles if args.candles is not None else int(payload.get("candles", 5000)),
        "fee_bps": args.fee_bps if args.fee_bps is not None else float(payload.get("fee_bps", 5.0)),
        "slippage_bps": args.slippage_bps if args.slippage_bps is not None else float(payload.get("slippage_bps", 2.0)),
        "initial_equity": args.initial_equity if args.initial_equity is not None else float(payload.get("initial_equity", 10000.0)),
    }


def main():
    parser=argparse.ArgumentParser(description="BGM Quant Lab BTC research MVP")
    parser.add_argument("--timeframe",default=None,choices=["1m","5m","15m","1h","4h","1d"])
    parser.add_argument("--candles",type=int,default=None)
    parser.add_argument("--candidates",type=int,default=100)
    parser.add_argument("--seed",type=int,default=7)
    parser.add_argument("--strategy-json",help="Run one user strategy exported by the dashboard")
    parser.add_argument("--fee-bps",type=float,default=None,help="Trading fee in basis points per side (overrides JSON)")
    parser.add_argument("--slippage-bps",type=float,default=None,help="Slippage assumption in basis points per side (overrides JSON)")
    parser.add_argument("--initial-equity",type=float,default=None,help="Starting capital in quote currency (overrides JSON)")
    parser.add_argument("--output",default="quant_lab/results")
    args=parser.parse_args()
    payload=None
    if args.strategy_json:
        try:
            payload=json.loads(Path(args.strategy_json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            parser.error(f"Cannot read strategy JSON: {exc}")
        if not isinstance(payload, dict):
            parser.error("Strategy JSON root must be an object.")
        candidates=[strategy_from_dict(payload.get("strategy", payload))]
    else:
        candidates=generate_candidates(args.candidates,args.seed)
    options=resolve_options(args,payload)
    timeframe=options["timeframe"]; candles=options["candles"]
    fee_bps=options["fee_bps"]; slippage_bps=options["slippage_bps"]
    initial_equity=options["initial_equity"]
    data=add_indicators(fetch_btc_candles(timeframe,candles))
    results=[]
    for strategy in candidates:
        try:
            report=train_test_report(data,strategy,fee_bps=fee_bps,
                                     slippage_bps=slippage_bps,
                                     initial_equity=initial_equity)
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
        "candles":len(data),"costs":{"fee_bps_per_side":fee_bps,
        "slippage_bps_per_side":slippage_bps},"initial_equity":initial_equity,
        "candidates":results},indent=2,allow_nan=False),encoding="utf-8")
    print(f"Processed {len(candidates)} candidates. Report: {target}")
    print("Research only: no orders are sent and profitability is not guaranteed.")

if __name__=="__main__":
    main()
