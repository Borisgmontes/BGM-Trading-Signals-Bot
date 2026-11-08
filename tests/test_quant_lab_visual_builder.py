import unittest
import pandas as pd
from quant_lab.indicators import add_indicators
from quant_lab.strategy import Condition, Strategy, strategy_from_dict
from quant_lab.backtest import run_backtest


class VisualBuilderEngineTests(unittest.TestCase):
    def test_indicator_events_include_crosses_and_exchange_opens(self):
        frame = pd.DataFrame({
            "open_time": pd.to_datetime([
                "2024-01-02T00:00:00Z", "2024-01-02T08:00:00Z",
                "2024-01-02T14:30:00Z"
            ]),
            "open": [100, 100, 100], "high": [101, 101, 101],
            "low": [99, 99, 99], "close": [100, 101, 102],
            "volume": [10, 11, 12],
        })
        result = add_indicators(frame)
        for feature in (
            "ema_10_cross_up_ema_20", "ema_20_cross_down_ema_50",
            "ema_50_cross_up_ema_200", "session_asia_open",
            "session_london_open", "session_new_york_open",
        ):
            self.assertIn(feature, result.columns)
        self.assertEqual(float(result.loc[0, "session_asia_open"]), 1.0)
        self.assertEqual(float(result.loc[1, "session_london_open"]), 1.0)
        self.assertEqual(float(result.loc[2, "session_new_york_open"]), 1.0)

    def test_json_round_trip_preserves_exit_rules(self):
        payload = {
            "name": "EMA Cross",
            "long_conditions": [{"feature": "ema_10_cross_up_ema_20", "operator": ">", "value": 0.5}],
            "short_conditions": [{"feature": "ema_10_cross_down_ema_20", "operator": ">", "value": 0.5}],
            "long_exit_conditions": [{"feature": "rsi_14", "operator": ">", "value": 70}],
            "short_exit_conditions": [{"feature": "rsi_14", "operator": "<", "value": 30}],
        }
        strategy = strategy_from_dict(payload)
        exported = strategy.to_dict()
        self.assertEqual(exported["long_exit_conditions"][0]["feature"], "rsi_14")
        self.assertEqual(exported["short_exit_conditions"][0]["value"], 30)

    def test_backtest_accepts_rule_based_exit_conditions(self):
        size = 260
        frame = pd.DataFrame({
            "open": [100.0] * size, "high": [101.0] * size,
            "low": [99.0] * size, "close": [100.0] * size,
            "atr_14": [1.0] * size, "rsi_14": [0.0] * size,
        })
        frame.loc[202:, "rsi_14"] = 80.0
        strategy = Strategy(
            "Exit by RSI",
            (Condition("close", ">", 0),),
            (Condition("close", "<", 0),),
            stop_atr=2.0, reward_risk=4.0, max_holding_bars=20,
            long_exit_conditions=(Condition("rsi_14", ">", 70),),
        )
        result = run_backtest(frame, strategy, fee_bps=0, slippage_bps=0)
        self.assertGreater(result.trades, 0)


if __name__ == "__main__":
    unittest.main()
