import pandas as pd

from radar_advanced import add_advanced_indicators, detect_fibonacci, detect_chart_patterns
from signal_tracker import resolve_directional_outcome


def sample_frame():
    rows = []
    for i in range(240):
        base = 100 + i * 0.08
        rows.append({
            "open_time": i * 300000, "open": base, "high": base + 1.2,
            "low": base - 1.0, "close": base + 0.4, "volume": 100 + i,
            "ema50": base, "rsi": 55,
        })
    return pd.DataFrame(rows)


def test_advanced_indicators_produce_expected_columns():
    frame = add_advanced_indicators(sample_frame())
    for name in ("adx", "vwap", "obv", "stoch_k", "stoch_d", "supertrend", "supertrend_dir"):
        assert name in frame.columns
    assert frame.iloc[-1]["vwap"] > 0


def test_fibonacci_returns_standard_retracement_levels():
    levels = detect_fibonacci(sample_frame())
    assert set(levels).issubset({"0.382", "0.5", "0.618", "0.786"})


def test_chart_pattern_detector_returns_a_list():
    assert isinstance(detect_chart_patterns(sample_frame()), list)


def test_long_signal_closes_automatically_at_target():
    assert resolve_directional_outcome("LONG", 105, 99, 98, 104) == ("WIN", "TAKE_PROFIT")


def test_short_signal_closes_automatically_at_stop():
    assert resolve_directional_outcome("SHORT", 103, 97, 102, 95) == ("LOSS", "STOP_LOSS")


def test_same_candle_touching_stop_and_target_is_conservative():
    assert resolve_directional_outcome("LONG", 105, 97, 98, 104) == (
        "LOSS", "BOTH_LEVELS_TOUCHED_SAME_CANDLE"
    )


def test_unreached_levels_do_not_expire_signal():
    assert resolve_directional_outcome("LONG", 103, 99, 98, 104) == (None, None)
