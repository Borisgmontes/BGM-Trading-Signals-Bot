import pandas as pd

from radar_engine import (evaluate_radar, validate_radar_config, format_radar_alert, estimate_probability, estimate_probability_details, _wilson_interval, qualifies_by_historical_probability)


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
    elif direction == "SHORT":
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


def test_probability_is_hidden_when_history_is_insufficient():
    assert estimate_probability(frame("LONG"), config(), "LONG") is None


def test_wilson_interval_is_bounded_and_narrows_with_more_samples():
    low_small, high_small = _wilson_interval(5, 10)
    low_large, high_large = _wilson_interval(50, 100)
    assert 0 <= low_small < 0.5 < high_small <= 1
    assert high_large - low_large < high_small - low_small


def test_probability_counts_unresolved_horizon_as_not_correct(monkeypatch):
    rows = []
    for i in range(260):
        rows.append({
            "open_time": i * 300000, "open": 100.0, "high": 101.0,
            "low": 99.0, "close": 100.0,
        })
    data = pd.DataFrame(rows)

    def always_long(history, cfg):
        return str(int(history.iloc[-1]["open_time"])), {
            "direction": "LONG", "stop": 90.0, "target": 110.0,
        }

    monkeypatch.setattr("radar_engine.evaluate_radar", always_long)
    result = estimate_probability_details(data, config(), "LONG")
    assert result["samples"] == 36
    assert result["wins"] == 0
    assert result["probability"] == 0
    assert result["ci_low"] == 0
    assert result["ci_high"] is not None


def test_probability_gate_requires_strictly_more_than_35_percent():
    assert qualifies_by_historical_probability({"probability": 36, "samples": 100}) is True
    assert qualifies_by_historical_probability({"probability": 35, "samples": 100}) is False
    assert qualifies_by_historical_probability({"probability": 14, "samples": 118}) is False
    assert qualifies_by_historical_probability({"probability": None, "samples": 29}) is False
