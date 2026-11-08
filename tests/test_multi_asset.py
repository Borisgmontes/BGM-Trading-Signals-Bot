import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from quant_lab.multi_asset import add_market_indicators, run_market_backtest
from quant_lab.api import app

class MultiAssetEngineTests(unittest.TestCase):
    @staticmethod
    def frame(n=900):
        x=np.arange(n,dtype=float)
        close=100 + x*.025 + 5*np.sin(x/13)
        return pd.DataFrame({
            "open":close-0.12,"high":close+0.8,"low":close-0.8,"close":close,
            "volume":1000+100*np.sin(x/7)**2,
            "open_time":pd.date_range("2024-01-01",periods=n,freq="h",tz="UTC")
        })

    def test_indicators_include_ema_vwap_atr(self):
        out=add_market_indicators(self.frame(),8,21,100)
        for col in ("ema_8","ema_21","ema_100","vwap","atr_14"):
            self.assertIn(col,out.columns)
        self.assertTrue(out["atr_14"].dropna().gt(0).all())

    def test_backtest_returns_equity_and_trade_log(self):
        result=run_market_backtest(self.frame(),{
            "ema_fast":8,"ema_slow":21,"ema_trend":100,"initial_equity":5000,
            "risk_per_trade_pct":1,"stop_atr":1.8,"reward_risk":2,
            "max_holding_bars":24,"use_vwap":False,"allow_short":True
        })
        self.assertEqual(result["initial_equity"],5000)
        self.assertGreaterEqual(result["final_equity"],0)
        self.assertIn("trade_log",result)
        self.assertIn("candles",result)
        self.assertEqual(len(result["equity_curve"]),result["trades"]+1)

    def test_invalid_ema_order_is_rejected(self):
        with self.assertRaises(ValueError):
            add_market_indicators(self.frame(),50,20,200)

class MultiAssetApiTests(unittest.TestCase):
    def setUp(self):
        self.client=app.test_client()

    def test_market_catalog(self):
        response=self.client.get("/api/markets")
        self.assertEqual(response.status_code,200)
        self.assertGreaterEqual(len(response.json["markets"]),15)

    @patch("quant_lab.api.fetch_market_data")
    def test_multi_asset_backtest_route(self,mock_data):
        mock_data.return_value=MultiAssetEngineTests.frame()
        response=self.client.post("/api/multi-backtest",json={
            "symbol":"BTC-USD","timeframe":"1h","candles":900,
            "config":{"ema_fast":8,"ema_slow":21,"ema_trend":100,
                      "initial_equity":2500,"use_vwap":False}
        })
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(response.json["result"]["initial_equity"],2500)
        self.assertIn("trade_log",response.json["result"])

if __name__=="__main__":
    unittest.main()
