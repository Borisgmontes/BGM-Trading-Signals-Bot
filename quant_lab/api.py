"""Small read-only HTTP API for BGM Quant Lab strategy research."""
from __future__ import annotations

from dataclasses import replace
from datetime import timezone
import pandas as pd
import math
from flask import Flask, jsonify, request
import hmac
import os
from . import analytics_store
from .data import fetch_btc_candles
from .indicators import add_indicators, normalize_indicator_settings
from .ranking import score_candidate, score_training_candidate
from .strategy import strategy_from_dict, TIMEFRAMES
from .backtest import run_backtest
from .validation import train_test_report
from .multi_asset import MARKETS, fetch_market_data, run_market_backtest
from .nlp import interpret_strategy

app = Flask(__name__)
ALLOWED_ORIGINS = {
    "https://bgm-quant-lab.onrender.com",
    "https://bgm-quant-lab-demo.onrender.com",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
}

@app.after_request
def add_cors(response):
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

@app.get("/")
def index():
    return jsonify({"service": "BGM Quant Lab API", "health": "/health", "mode": "research-only"})

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
    settings = normalize_indicator_settings(strategy.indicator_settings)
    strategy = replace(strategy, indicator_settings=settings)
    for rule in (*strategy.long_conditions, *strategy.short_conditions, *strategy.long_exit_conditions, *strategy.short_exit_conditions):
        rule_tf = rule.timeframe or timeframe
        if TIMEFRAMES[rule_tf] < TIMEFRAMES[timeframe]:
            raise ValueError(f"Rule timeframe {rule_tf} is lower than execution timeframe {timeframe}. Use the execution timeframe or a higher one to avoid look-ahead.")
        for feature in (rule.feature, rule.value if isinstance(rule.value, str) else None):
            if not feature: continue
            if feature.startswith("ema_") and "_cross_" not in feature:
                period=int(feature.split("_")[1])
                if period not in settings["ema_periods"]:
                    raise ValueError(f"EMA {period} is used by a rule but is not included in indicator_settings. Add it to EMA periods.")
            if "_cross_" in feature:
                parts=feature.split("_")
                pair=[int(parts[1]),int(parts[-1])]
                if pair not in settings["cross_pairs"]:
                    raise ValueError(f"EMA cross {pair[0]}/{pair[1]} is used by a rule but is not included in cross_pairs.")
            if feature.startswith(("rsi_","atr_")):
                expected=settings["rsi_period"] if feature.startswith("rsi_") else settings["atr_period"]
                if int(feature.split("_")[1])!=expected: raise ValueError(f"Rule feature {feature} does not match configured period {expected}.")
            if feature.startswith(("bb_upper_","bb_lower_")) and int(feature.rsplit("_",1)[1])!=settings["bb_period"]:
                raise ValueError(f"Rule feature {feature} does not match configured Bollinger period {settings['bb_period']}.")
            if feature.startswith("volume_ratio_") and int(feature.rsplit("_",1)[1])!=settings["volume_period"]:
                raise ValueError(f"Rule feature {feature} does not match configured volume period {settings['volume_period']}.")
            if feature.startswith("macd_hist_"):
                parts=feature.split("_")
                configured=[settings["macd_fast"],settings["macd_slow"],settings["macd_signal"]]
                if list(map(int,parts[2:]))!=configured:
                    raise ValueError(f"Rule feature {feature} does not match configured MACD {configured}.")
    return strategy, timeframe, candles, fee, slippage, equity

def _market_data(timeframe, candles, strategy=None):
    settings = strategy.indicator_settings if strategy else None
    base = add_indicators(fetch_btc_candles(timeframe=timeframe, limit=candles), settings)
    if len(base) < 500:
        raise ValueError(f"Only {len(base)} closed candles available; need at least 500.")
    # Every explicit timeframe gets a namespaced, causal feature set. Higher-TF
    # values become visible only after that candle has closed (never at its open).
    needed = {rule.timeframe for rule in (
        (*strategy.long_conditions, *strategy.short_conditions,
         *strategy.long_exit_conditions, *strategy.short_exit_conditions)
        if strategy else ()) if rule.timeframe}
    needed.add(timeframe)
    for tf in sorted(needed, key=lambda value: TIMEFRAMES[value]):
        if tf == timeframe:
            source = base
        else:
            source = add_indicators(fetch_btc_candles(timeframe=tf, limit=candles), settings)
        features = [column for column in source.columns if column not in {
            "open_time","open","high","low","close","volume","close_time",
            "quote_volume","trades","taker_buy_base","taker_buy_quote","ignore"
        }]
        available = source[["open_time", *features]].copy()
        if tf != timeframe:
            available["available_at"] = available["open_time"] + pd.to_timedelta(TIMEFRAMES[tf], unit="s")
            available = available.drop(columns=["open_time"])
            available.rename(columns={column:f"tf_{tf}__{column}" for column in features},inplace=True)
            base = pd.merge_asof(base.sort_values("open_time"),
                available.sort_values("available_at"),
                left_on="open_time",right_on="available_at",direction="backward")
            base = base.drop(columns=["available_at"])
        else:
            for column in features:
                base[f"tf_{tf}__{column}"] = base[column]
    return base

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

@app.route("/api/interpret", methods=["POST", "OPTIONS"])
def interpret():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return jsonify({"ok": True, **interpret_strategy(payload.get("description", ""), payload.get("name"))})
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Strategy interpretation failed")
        return jsonify({"ok": False, "error": "Interpretation failed. Check API logs and retry."}), 502


@app.route("/api/backtest", methods=["POST", "OPTIONS"])
def backtest():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        strategy, timeframe, candles, fee, slippage, equity = _load_request(request.get_json(silent=True))
        frame = _market_data(timeframe, candles, strategy)
        full = run_backtest(frame, strategy, fee, slippage, equity)
        validation = train_test_report(frame, strategy, fee_bps=fee, slippage_bps=slippage, initial_equity=equity)
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
    except Exception as exc:
        app.logger.exception("Backtest failed")
        return jsonify({"ok": False, "error": "Backtest failed: " + str(exc)[:300]}), 502

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
        frame = _market_data(timeframe, candles, strategy)
        split = int(len(frame) * .70)
        train_frame = frame.iloc[:split].reset_index(drop=True)
        rows = []
        for stop in stops:
            for target in targets:
                candidate = replace(strategy, stop_atr=stop, reward_risk=target)
                train_result = run_backtest(train_frame, candidate, fee, slippage, equity)
                training_quality = score_training_candidate(train_result.to_dict())
                rows.append({
                    "stop_atr": stop, "reward_risk": target,
                    "trades_train": train_result.trades,
                    "win_rate_train_pct": round(train_result.win_rate_pct, 4),
                    "profit_factor_train": train_result.profit_factor,
                    "net_return_train_pct": round(train_result.net_return_pct, 4),
                    "max_drawdown_train_pct": round(train_result.max_drawdown_pct, 4),
                    "training_score": training_quality["training_score"],
                    "training_gates": training_quality["training_gates"]
                })
        rows.sort(key=lambda x: (x["training_score"], x["net_return_train_pct"]), reverse=True)
        best = rows[0]
        selected_strategy = replace(strategy, stop_atr=best["stop_atr"], reward_risk=best["reward_risk"])
        validation = train_test_report(frame, selected_strategy, fee_bps=fee, slippage_bps=slippage, initial_equity=equity)
        selected_test = validation["out_of_sample"]
        selected_quality = score_candidate(validation)
        return jsonify({
            "ok": True, "market": "BTCUSDT", "timeframe": timeframe,
            "candles_used": len(frame), "combinations_tested": len(rows),
            "ranking": rows,
            "selected": {
                "stop_atr": best["stop_atr"], "reward_risk": best["reward_risk"],
                "out_of_sample": _safe_result_from_dict(selected_test),
                "quality": selected_quality
            },
            "warning": "Las combinaciones se ordenaron solo con datos TRAIN. La combinación ganadora se evaluó una sola vez en datos OUT-OF-SAMPLE. No selecciones parámetros mirando repetidamente el OOS."
        })

    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("Optimization failed")
        return jsonify({"ok": False, "error": "Optimization failed: " + str(exc)[:300]}), 502


@app.get("/api/markets")
def markets():
    return jsonify({"ok": True, "markets": [{"symbol": k, "name": v} for k, v in MARKETS.items()],
                    "timeframes": ["5m", "15m", "1h", "4h", "1d"]})

@app.route("/api/multi-backtest", methods=["POST", "OPTIONS"])
def multi_backtest():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        payload = request.get_json(silent=True) or {}
        symbol = str(payload.get("symbol", "BTC-USD")).upper()
        timeframe = str(payload.get("timeframe", "1h"))
        candles = int(payload.get("candles", 1500))
        config = payload.get("config", {})
        if not isinstance(config, dict):
            raise ValueError("config debe ser un objeto JSON.")
        frame = fetch_market_data(symbol, timeframe, candles)
        result = run_market_backtest(frame, config)
        split = int(len(frame) * 0.70)
        train_result = run_market_backtest(frame.iloc[:split].reset_index(drop=True), config)
        warmup = max(200, int(config.get("ema_trend", 200)))
        oos_start = max(0, split - warmup)
        oos_result = run_market_backtest(frame.iloc[oos_start:].reset_index(drop=True), config)
        def compact(report):
            keys = ("initial_equity", "final_equity", "net_profit", "trades", "wins",
                    "losses", "win_rate_pct", "profit_factor", "max_drawdown_pct", "net_return_pct")
            return {key: report[key] for key in keys}
        return jsonify({"ok": True, "symbol": symbol, "market_name": MARKETS[symbol],
                        "timeframe": timeframe, "candles_used": len(frame),
                        "data_start": frame["open_time"].iloc[0].isoformat(),
                        "data_end": frame["open_time"].iloc[-1].isoformat(),
                        "result": result,
                        "validation": {"train": compact(train_result), "out_of_sample": compact(oos_result),
                                       "train_fraction": 0.70,
                                       "note": "Estrategia fija; 30% final fuera de muestra. Evita optimizar mirando repetidamente el OOS."},
                        "disclaimer": "Simulación histórica. No predice resultados ni ejecuta órdenes."})
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        app.logger.exception("Multi-asset backtest failed")
        return jsonify({"ok": False, "error": str(exc)[:500]}), 502


# Anonymous product analytics. Separate PostgreSQL tables; no trading or Radar data.
@app.route("/api/analytics/event", methods=["POST", "OPTIONS"])
def analytics_event():
    if request.method == "OPTIONS":
        return ("", 204)
    if not analytics_store.is_configured():
        return jsonify({"ok": False, "error": "Analytics storage is not configured."}), 503
    try:
        payload = request.get_json(silent=True) or {}
        analytics_store.record_event(payload)
        return jsonify({"ok": True}), 202
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Analytics event could not be stored")
        return jsonify({"ok": False, "error": "Analytics storage unavailable."}), 503

@app.get("/api/analytics/report")
def analytics_report():
    expected = os.getenv("QUANT_ADMIN_TOKEN", "")
    supplied = request.headers.get("Authorization", "")
    if not expected:
        return jsonify({"ok": False, "error": "Admin access is not configured."}), 503
    if not hmac.compare_digest(supplied, "Bearer " + expected):
        return jsonify({"ok": False, "error": "Unauthorized."}), 401
    if not analytics_store.is_configured():
        return jsonify({"ok": False, "error": "Analytics storage is not configured."}), 503
    try:
        days = int(request.args.get("days", "1"))
        return jsonify(analytics_store.daily_report(days))
    except (ValueError, TypeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        app.logger.exception("Analytics report failed")
        return jsonify({"ok": False, "error": "Analytics report unavailable."}), 503
