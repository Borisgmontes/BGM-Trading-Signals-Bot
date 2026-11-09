"""Deterministic out-of-sample BTC RADAR backtest.

Uses closed candles only, one position at a time, TP-before-SL ordering and
conservative same-candle handling. No fees/slippage are assumed unless passed.
"""
from radar_engine import evaluate_radar, validate_radar_config
from signal_tracker import resolve_directional_outcome


def _summarize(trades):
    if not trades:
        return {
            "trades": 0, "wins": 0, "losses": 0, "no_hit": 0,
            "win_rate": None, "expectancy_r": None, "profit_factor": None,
            "net_r": 0.0, "max_drawdown_r": 0.0,
        }
    wins = sum(t["result"] == "WIN" for t in trades)
    losses = len(trades) - wins
    values = [float(t["net_r"]) for t in trades]
    positive = sum(v for v in values if v > 0)
    negative = abs(sum(v for v in values if v < 0))
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": len(trades), "wins": wins, "losses": losses,
        "no_hit": sum(t["reason"] == "HORIZON_EXPIRED" for t in trades),
        "win_rate": round(100 * wins / len(trades), 1),
        "expectancy_r": round(sum(values) / len(values), 3),
        "profit_factor": round(positive / negative, 2) if negative else (None if not positive else "∞"),
        "net_r": round(sum(values), 2), "max_drawdown_r": round(drawdown, 2),
    }


def run_backtest(df, config, horizon=20, test_fraction=0.30,
                 fee_bps_per_side=0.0, slippage_bps_per_side=0.0, higher_df=None):
    """Evaluate only the final test_fraction of candles; earlier bars warm indicators.

    A missed TP/SL by the horizon is classified as a non-win and closed at the
    final horizon close for R accounting. Costs are optional basis points per side.
    """
    validate_radar_config(config)
    if horizon < 1 or not 0.1 <= float(test_fraction) <= 0.5:
        raise ValueError("Horizonte o fracción de prueba no válidos.")
    if fee_bps_per_side < 0 or slippage_bps_per_side < 0:
        raise ValueError("Los costes no pueden ser negativos.")
    first_test = max(204, int(len(df) * (1.0 - float(test_fraction))))
    if len(df) - first_test <= horizon:
        raise ValueError("No hay suficientes velas para el período fuera de muestra.")
    trades = []
    i = first_test
    while i < len(df) - horizon:
        history = df.iloc[:i + 1]
        historical_higher = higher_df
        if config.get("higher_timeframe", "none") != "none" and higher_df is not None:
            cutoff = int(history.iloc[-1].get("close_time", history.iloc[-1]["open_time"]))
            historical_higher = higher_df[higher_df["close_time"] <= cutoff]
        _, signal = evaluate_radar(history, config, historical_higher)
        if not signal:
            i += 1
            continue
        direction = signal["direction"]
        entry = float(signal["entry"])
        stop = float(signal["stop"])
        target = float(signal["target"])
        risk = abs(entry - stop)
        if risk <= 0:
            i += 1
            continue
        future = df.iloc[i + 1:i + horizon + 1]
        result = None
        reason = "HORIZON_EXPIRED"
        exit_price = float(future.iloc[-1]["close"])
        exit_index = i + horizon
        for offset, (_, candle) in enumerate(future.iterrows(), start=1):
            result, reason = resolve_directional_outcome(
                direction, candle["high"], candle["low"], stop, target
            )
            if result:
                exit_price = target if reason == "TAKE_PROFIT" else stop
                exit_index = i + offset
                break
            result = None
        if result is None:
            result = "LOSS"
            reason = "HORIZON_EXPIRED"
        sign = 1.0 if direction == "LONG" else -1.0
        gross_r = sign * (exit_price - entry) / risk
        cost_price = 2.0 * (float(fee_bps_per_side) + float(slippage_bps_per_side)) / 10000.0 * entry
        net_r = gross_r - cost_price / risk
        trades.append({
            "candle_id": str(int(df.iloc[i]["open_time"])),
            "direction": direction, "result": result, "reason": reason,
            "gross_r": round(gross_r, 4), "net_r": round(net_r, 4),
            "entry": entry, "exit": exit_price,
        })
        # Do not count overlapping positions as independent trades.
        i = max(i + 1, exit_index + 1)
    return {
        "method": "out_of_sample_last_30_percent_non_overlapping",
        "test_start_index": first_test, "test_candles": len(df) - first_test,
        "horizon_candles": int(horizon),
        "costs": {
            "fee_bps_per_side": float(fee_bps_per_side),
            "slippage_bps_per_side": float(slippage_bps_per_side),
        },
        "metrics": _summarize(trades),
        "trades": trades[-100:],
        "cost_warning": "Si los costes son 0, los resultados son brutos y no representan rentabilidad neta.",
    }
