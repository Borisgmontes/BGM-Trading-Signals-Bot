import unittest
from unittest.mock import patch
import pandas as pd
from quant_lab.indicators import add_indicators, normalize_indicator_settings
from quant_lab.strategy import Condition, Strategy, strategy_from_dict
from quant_lab.backtest import run_backtest
from quant_lab.api import _market_data


class ConfigurableMultiTimeframeTests(unittest.TestCase):
    def test_custom_indicator_periods_are_generated(self):
        frame = pd.DataFrame({
            "open_time": pd.date_range("2024-01-01", periods=600, freq="5min", tz="UTC"),
            "open": [100.0+i*.01 for i in range(600)],
            "high": [101.0+i*.01 for i in range(600)],
            "low": [99.0+i*.01 for i in range(600)],
            "close": [100.0+i*.01 for i in range(600)],
            "volume": [10.0+i*.01 for i in range(600)],
        })
        settings = normalize_indicator_settings({
            "ema_periods": [7, 21, 55],
            "cross_pairs": [[7, 21], [21, 55]],
            "rsi_period": 9, "atr_period": 11, "bb_period": 30,
            "bb_std": 2.5, "macd_fast": 8, "macd_slow": 21,
            "macd_signal": 5, "volume_period": 17,
        })
        result = add_indicators(frame, settings)
        for feature in ("ema_7", "ema_21", "ema_55", "rsi_9", "atr_11",
                        "bb_upper_30", "bb_lower_30", "macd_hist_8_21_5",
                        "volume_ratio_17", "ema_7_cross_up_ema_21"):
            self.assertIn(feature, result.columns)

    def test_strategy_json_preserves_periods_and_timeframe(self):
        payload = {
            "name": "H1 Trend / M5 Trigger",
            "indicator_settings": {"ema_periods": [20, 200]},
            "long_conditions": [{"feature": "ema_200", "operator": ">", "value": 0, "timeframe": "1h"}],
            "short_conditions": [{"feature": "ema_200", "operator": "<", "value": 0, "timeframe": "1h"}],
        }
        strategy = strategy_from_dict(payload)
        exported = strategy.to_dict()
        self.assertEqual(exported["long_conditions"][0]["timeframe"], "1h")
        self.assertEqual(exported["indicator_settings"]["ema_periods"], [20, 200])

    def test_backtest_reads_namespaced_higher_timeframe_features(self):
        size = 260
        frame = pd.DataFrame({
            "open": [100.0]*size, "high": [101.0]*size,
            "low": [99.0]*size, "close": [100.0]*size, "atr_14": [1.0]*size,
            "tf_1h__rsi_9": [40.0]*size,
        })
        strategy = Strategy(
            "H1 filter",
            (Condition("rsi_9", "<", 60, "1h"),),
            (Condition("rsi_9", ">", 60, "1h"),),
            indicator_settings={"atr_period": 14},
        )
        result = run_backtest(frame, strategy, fee_bps=0, slippage_bps=0)
        self.assertGreater(result.trades, 0)

    def test_higher_timeframe_values_only_appear_after_close(self):
        base_times = pd.date_range("2024-01-01", periods=600, freq="5min", tz="UTC")
        hour_times = pd.date_range("2024-01-01", periods=600, freq="1h", tz="UTC")
        def frame(times):
            n=len(times)
            return pd.DataFrame({
                "open_time": times, "open": [100.0]*n, "high": [101.0]*n,
                "low": [99.0]*n, "close": [100.0]*n, "volume": [10.0]*n,
            })
        def fake_fetch(timeframe, limit):
            return frame(hour_times if timeframe=="1h" else base_times)
        strategy = Strategy(
            "No lookahead",
            (Condition("ema_10", ">", 0, "1h"),),
            (Condition("ema_10", "<", 0, "1h"),),
        )
        with patch("quant_lab.api.fetch_btc_candles", side_effect=fake_fetch):
            merged = _market_data("5m", 500, strategy)
        self.assertTrue(pd.isna(merged.loc[0, "tf_1h__ema_10"]))
        first_hour_close = merged.index[merged["open_time"] == pd.Timestamp("2024-01-01T01:00:00Z")][0]
        self.assertTrue(pd.notna(merged.loc[first_hour_close, "tf_1h__ema_10"]))


if __name__ == "__main__":
    unittest.main()
