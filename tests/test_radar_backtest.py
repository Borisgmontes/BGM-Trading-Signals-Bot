import pandas as pd

from radar_backtest import run_backtest


def _frame():
    return pd.DataFrame([
        {"open_time": i * 300000, "high": 103.0, "low": 100.0, "close": 100.5}
        for i in range(260)
    ])


def _config():
    return {"symbol":"BTCUSDT","timeframe":"5m","modules":["trend"],
            "min_score":1,"target_r":2.0}


def test_backtest_reports_non_overlapping_out_of_sample_trades(monkeypatch):
    def always_long(history, config):
        return str(int(history.iloc[-1]["open_time"])), {
            "direction":"LONG","entry":100.0,"stop":99.0,"target":102.0,
        }

    monkeypatch.setattr("radar_backtest.evaluate_radar", always_long)
    result = run_backtest(_frame(), _config(), horizon=2, test_fraction=0.2)
    assert result["method"].startswith("out_of_sample")
    assert result["metrics"]["trades"] > 0
    assert result["metrics"]["wins"] == result["metrics"]["trades"]
    assert result["metrics"]["expectancy_r"] == 2.0
    assert result["metrics"]["max_drawdown_r"] == 0.0


def test_backtest_counts_unresolved_horizon_as_non_win(monkeypatch):
    data = _frame()
    data["high"] = 101.0
    data["low"] = 100.0
    data["close"] = 100.5

    def always_long(history, config):
        return str(int(history.iloc[-1]["open_time"])), {
            "direction":"LONG","entry":100.0,"stop":99.0,"target":102.0,
        }

    monkeypatch.setattr("radar_backtest.evaluate_radar", always_long)
    result = run_backtest(data, _config(), horizon=2, test_fraction=0.2)
    assert result["metrics"]["trades"] > 0
    assert result["metrics"]["wins"] == 0
    assert result["metrics"]["no_hit"] == result["metrics"]["trades"]
    assert result["trades"][0]["reason"] == "HORIZON_EXPIRED"


def test_backtest_applies_explicit_round_trip_costs(monkeypatch):
    def always_long(history, config):
        return str(int(history.iloc[-1]["open_time"])), {
            "direction":"LONG","entry":100.0,"stop":99.0,"target":102.0,
        }

    monkeypatch.setattr("radar_backtest.evaluate_radar", always_long)
    free = run_backtest(_frame(), _config(), horizon=2, test_fraction=0.2)
    costly = run_backtest(_frame(), _config(), horizon=2, test_fraction=0.2,
                          fee_bps_per_side=10, slippage_bps_per_side=5)
    assert costly["metrics"]["net_r"] < free["metrics"]["net_r"]
