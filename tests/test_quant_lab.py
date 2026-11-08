import unittest
import pandas as pd
from quant_lab.indicators import add_indicators
from quant_lab.strategy import Condition,Strategy,generate_candidates
from quant_lab.backtest import run_backtest
from quant_lab.validation import monte_carlo_trade_bootstrap
from quant_lab.ranking import score_candidate

class QuantLabTests(unittest.TestCase):
    @staticmethod
    def candles(n=700):
        close=[100+i*.05+((i%17)-8)*.2 for i in range(n)]
        return pd.DataFrame({"open":close,"high":[x+1 for x in close],"low":[x-1 for x in close],"close":close,"volume":[1000+(i%13)*20 for i in range(n)]})
    def test_indicators_are_added(self):
        result=add_indicators(self.candles())
        self.assertIn("ema_200",result); self.assertIn("atr_14",result); self.assertIn("rsi_14",result)
    def test_generator_is_reproducible(self):
        self.assertEqual([x.strategy_id for x in generate_candidates(20,42)],[x.strategy_id for x in generate_candidates(20,42)])
    def test_backtest_returns_metrics(self):
        data=add_indicators(self.candles())
        strategy=Strategy("test",(Condition("close",">","ema_200"),),(Condition("close","<","ema_200"),))
        result=run_backtest(data,strategy)
        self.assertGreaterEqual(result.trades,0)
        self.assertTrue(-100<=result.net_return_pct<1000000)
    def test_monte_carlo_is_reproducible(self):
        a=monte_carlo_trade_bootstrap([1,-.5,2,-1],200,3)
        b=monte_carlo_trade_bootstrap([1,-.5,2,-1],200,3)
        self.assertEqual(a,b)
    def test_quality_gate_rejects_small_samples(self):
        report={"train":{"net_return_pct":20},"out_of_sample":{"trades":4,"profit_factor":2.0,"max_drawdown_pct":3,"net_return_pct":5,"expectancy_pct":1}}
        self.assertFalse(score_candidate(report)["eligible_for_paper_testing"])

if __name__=="__main__": unittest.main()
