import pandas as pd

from radar_engine import evaluate_radar, validate_radar_config, format_radar_alert


def config(**overrides):
    value = {
        "symbol": "BTCUSDT", "timeframe": "5m", "modules": ["trend"],
        "min_score": 1, "target_r": 2.0, "name": "BTC RADAR test",
    }
    value.update(overrides)
    return value


def frame(direction="LONG"):
    rows = []
    for i in range(220):
        rows.append({
            "open_time": i * 300000, "open": 99.0, "high": 101.0,
            "low": 98.0, "close": 100.0, "volume": 100.0,
            "ema20": 100.0, "ema50": 100.0, "ema200": 100.0,
            "rsi": 50.0, "macd_hist": 0.0, "atr": 2.0,
            "vol_sma20": 100.0, "bb_upper": 102.0, "bb_lower": 98.0,
        })
    last = rows[-1]
    if direction == "LONG":
        last.update({"open": 108.0, "high": 112.0, "low": 107.0,
                     "close": 110.0, "ema20": 109.0, "ema50": 105.0,
                     "ema200": 100.0})
    else:
        last.update({"open": 92.0, "high": 93.0, "low": 88.0,
                     "close": 90.0, "ema20": 91.0, "ema50": 95.0,
                     "ema200": 100.0})
    return pd.DataFrame(rows)


def test_config_rejects_invalid_score():
    try:
        validate_radar_config(config(min_score=2))
    except ValueError:
        return
    raise AssertionError("min_score cannot exceed active modules")


def test_radar_emits_long_on_closed_candle():
    candle_id, signal = evaluate_radar(frame("LONG"), config())
    assert candle_id == str(219 * 300000)
    assert signal["direction"] == "LONG"
    assert signal["target"] > signal["entry"] > signal["stop"]
    assert "Tendencia EMA" in signal["confirmations"]
    assert "BTC RADAR" in format_radar_alert(signal)


def test_radar_emits_short_on_closed_candle():
    candle_id, signal = evaluate_radar(frame("SHORT"), config())
    assert candle_id == str(219 * 300000)
    assert signal["direction"] == "SHORT"
    assert signal["stop"] > signal["entry"] > signal["target"]


def test_radar_no_signal_when_trend_is_flat():
    candle_id, signal = evaluate_radar(frame("FLAT"), config())
    assert candle_id == str(219 * 300000)
    assert signal is None
