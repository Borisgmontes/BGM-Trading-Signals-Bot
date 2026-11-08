import unittest
from unittest.mock import patch
import pandas as pd
from quant_lab.api import app
from tests.test_quant_lab import QuantLabTests

class QuantLabApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.frame = QuantLabTests.candles(900)
        self.frame["open_time"] = pd.date_range("2024-01-01", periods=len(self.frame), freq="5min", tz="UTC")
        payload = {
            "name": "API test",
            "long_conditions": [{"feature": "close", "operator": ">", "value": "ema_200"}],
            "short_conditions": [{"feature": "close", "operator": "<", "value": "ema_200"}],
            "stop_atr": 1.8, "reward_risk": 2.0, "max_holding_bars": 24
        }
        self.payload = {"strategy": payload, "timeframe": "5m", "candles": 700}

    def test_health_endpoint(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "ok")

    @patch("quant_lab.api._market_data")
    def test_backtest_endpoint_returns_real_engine_metrics(self, market_data):
        from quant_lab.indicators import add_indicators
        market_data.return_value = add_indicators(self.frame)
        response = self.client.post("/api/backtest", json=self.payload)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertTrue(response.json["ok"])
        self.assertIn("out_of_sample", response.json)
        self.assertIn("profit_factor", response.json["out_of_sample"])

    @patch("quant_lab.api._market_data")
    def test_optimizer_tests_parameter_grid(self, market_data):
        from quant_lab.indicators import add_indicators
        market_data.return_value = add_indicators(self.frame)
        payload = {**self.payload, "stop_atr_values": [1.5, 2.0], "reward_risk_values": [2.0, 2.5]}
        response = self.client.post("/api/optimize", json=payload)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json["combinations_tested"], 4)

    def test_rejects_oversized_candle_request(self):
        response = self.client.post("/api/backtest", json={**self.payload, "candles": 50000})
        self.assertEqual(response.status_code, 400)

if __name__ == "__main__":
    unittest.main()
