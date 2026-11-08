"""Small read-only HTTP API for BGM Quant Lab strategy research."""
from __future__ import annotations

from dataclasses import replace
from datetime import timezone
import math
from flask import Flask, jsonify, request
from .data import fetch_btc_candles
from .indicators import add_indicators
from .ranking import score_candidate
from .strategy import strategy_from_dict
from .backtest import run_backtest
from .validation import train_test_report

app = Flask(__name__)
ALLOWED_ORIGINS = {
    "https://bgm-quant-lab.onrender.com",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
}

@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "bgm-quant-lab-api", "mode": "research-only"})

def _number(value, name, low, high):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric.")
    if not math.isfinite(result) or result < low or result > high:
        raise ValueError(f"{name} must be between {low} and {high}.")
    return result

def _load_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object.")
    raw = payload.get("strategy", payload)
    if isinstance(raw, dict) and "strategy" in raw and "long_conditions" not in raw:
        raw = raw["strategy"]
    strategy = strategy_from_dict(raw)
    timeframe = payload.get("timeframe", "5m")
    if timeframe not in {"1m", "5m", "15m", "1h", "4h", "1d"}:
        raise ValueError("Unsupported timeframe.")
    candles = int(payload.get("candles", 5000))
    if candles < 500 or candles > 20000:
        raise ValueError("candles must be between 500 and 20000.")
    fee = _number(payload.get("fee_bps", 5), "fee_bps", 0, 100)
    slippage = _number(payload.get("slippage_bps", 2), "slippage_bps", 0, 100)
    equity = _number(payload.get("initial_equity", 10000), "initial_equity", 1, 1e9)
    return strategy, timeframe, candles, fee, slippage, equity

def _market_data(timeframe, candles):
    frame = add_indicators(fetch_btc_candles(timeframe=timeframe, limit=candles))
    if len(frame) < 500:
        raise ValueError(f"Only {len(frame)} closed candles available; need at least 500.")
    return frame

def _safe_result(result):
    data = result.to_dict()
    for key in ("win_rate_pct", "expectancy_pct", "net_return_pct",
                "max_drawdown_pct", "average_trade_pct"):
        data[key] = round(float(data[key]), 6)
    if data["profit_factor"] is not None:
        data["profit_factor"] = round(float(data["profit_factor"]), 6)
    data["equity_curve"] = [round(float(x), 6) for x in data["equity_curve"]]
    data["trade_returns_pct"] = [round(float(x), 6) for x in data["trade_returns_pct"]]
    return data

@app.route("/api/backtest", methods=["POST", "OPTIONS"])
def backtest():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        strategy, timeframe, candles, fee, slippage, equity = _load_request(request.get_json(silent=True))
        frame = _market_data(timeframe, candles)
        full = run_backtest(frame, strategy, fee, slippage, equity)
        validation = train_test_report(frame, strategy, fee_bps=fee, slippage_bps=slippage)
        quality = score_candidate(validation)
        return jsonify({
            "ok": True, "market": "BTCUSDT", "timeframe": timeframe,
            "candles_used": len(frame),
            "data_start": frame["open_time"].iloc[0].isoformat(),
            "data_end": frame["open_time"].iloc[-1].isoformat(),
            "strategy": strategy.to_dict(),
            "full_sample": _safe_result(full),
            "train": _safe_result_from_dict(validation["train"]),
            "out_of_sample": _safe_result_from_dict(validation["out_of_sample"]),
            "quality": quality,
            "costs": {"fee_bps_per_side": fee, "slippage_bps_per_side": slippage},
            "disclaimer": "Historical simulation only. Not a prediction or investment recommendation."
        })
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Backtest failed")
        return jsonify({"ok": False, "error": "Backtest failed. Check API logs and retry."}), 502

def _safe_result_from_dict(data):
    result = dict(data)
    for key in ("win_rate_pct", "expectancy_pct", "net_return_pct",
                "max_drawdown_pct", "average_trade_pct"):
        result[key] = round(float(result[key]), 6)
    if result.get("profit_factor") is not None:
        result["profit_factor"] = round(float(result["profit_factor"]), 6)
    result["equity_curve"] = [round(float(x), 6) for x in result["equity_curve"]]
    result["trade_returns_pct"] = [round(float(x), 6) for x in result["trade_returns_pct"]]
    return result

@app.route("/api/optimize", methods=["POST", "OPTIONS"])
def optimize():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        payload = request.get_json(silent=True) or {}
        strategy, timeframe, candles, fee, slippage, equity = _load_request(payload)
        stops = payload.get("stop_atr_values", [1.2, 1.8, 2.4])
        targets = payload.get("reward_risk_values", [1.5, 2.0, 2.5])
        if not isinstance(stops, list) or not isinstance(targets, list) or not stops or not targets:
            raise ValueError("Parameter grids must be non-empty arrays.")
        if len(stops) * len(targets) > 25:
            raise ValueError("Maximum 25 parameter combinations per optimization.")
        stops = [_number(x, "stop_atr", .5, 5) for x in stops]
        targets = [_number(x, "reward_risk", .5, 6) for x in targets]
        frame = _market_data(timeframe, candles)
        rows = []
        for stop in stops:
            for target in targets:
                candidate = replace(strategy, stop_atr=stop, reward_risk=target)
                report = train_test_report(frame, candidate, fee_bps=fee, slippage_bps=slippage)
                test = report["out_of_sample"]
                quality = score_candidate(report)
                rows.append({
                    "stop_atr": stop, "reward_risk": target,
                    "trades": test["trades"],
                    "win_rate_pct": round(test["win_rate_pct"], 4),
                    "profit_factor": test["profit_factor"],
                    "net_return_pct": round(test["net_return_pct"], 4),
                    "max_drawdown_pct": round(test["max_drawdown_pct"], 4),
                    "research_score": quality["research_score"],
                    "eligible_for_paper_testing": quality["eligible_for_paper_testing"]
                })
        rows.sort(key=lambda x: (x["research_score"], x["net_return_pct"]), reverse=True)
        return jsonify({
            "ok": True, "market": "BTCUSDT", "timeframe": timeframe,
            "candles_used": len(frame), "combinations_tested": len(rows),
            "ranking": rows,
            "warning": "Parameter search can overfit. Treat this as exploratory; confirm with walk-forward and unseen data."
        })
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Optimization failed")
        return jsonify({"ok": False, "error": "Optimization failed. Check API logs and retry."}), 502
