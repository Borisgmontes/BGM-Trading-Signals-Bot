import unittest
import pandas as pd

from strategy_engine import validate_config, evaluate


class StrategyEngineTests(unittest.TestCase):
    def valid_config(self):
        return {
            "name": "test", "symbol": "BTCUSDT", "timeframe": "5m",
            "entry": "breakout", "trend": "none", "confirmation": "none",
            "stop": "atr", "target_r": 2.0, "risk_pct": 0.5,
        }

    def test_valid_config(self):
        self.assertEqual(validate_config(self.valid_config())["symbol"], "BTCUSDT")

    def test_rejects_unknown_symbol(self):
        config = self.valid_config()
        config["symbol"] = "FAKEUSDT"
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_rejects_unsafe_risk_value(self):
        config = self.valid_config()
        config["risk_pct"] = 25
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_no_signal_without_setup(self):
        # Flat candles have no breakout; all indicator columns are supplied explicitly.
        df = pd.DataFrame({
            "open_time": list(range(220)),
            "open": [100.0] * 220, "high": [101.0] * 220,
            "low": [99.0] * 220, "close": [100.0] * 220,
            "volume": [1000.0] * 220, "ema20": [100.0] * 220,
            "ema50": [100.0] * 220, "ema200": [100.0] * 220,
            "atr": [2.0] * 220, "vol_sma20": [1000.0] * 220,
        })
        candle_id, signal = evaluate(df, self.valid_config())
        self.assertEqual(candle_id, "219")
        self.assertIsNone(signal)


if __name__ == "__main__":
    unittest.main()
