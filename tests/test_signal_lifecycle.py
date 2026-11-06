import pandas as pd
import dashboard_api as api


def test_auto_tracker_closes_long_only_when_tp_or_sl_touched(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api._MEM_SIGNALS.clear()
    api._MEM_SIGNALS.append({
        "id":"1","candle_id":"300000","timeframe":"5m","direction":"LONG",
        "entry":100.0,"stop":98.0,"target":104.0,"status":"CONFIRMED","result":None,
    })
    candles=pd.DataFrame([
        {"open_time":300000,"high":101.0,"low":99.0},
        {"open_time":600000,"high":103.0,"low":99.0},
        {"open_time":900000,"high":105.0,"low":100.0},
    ])
    closed=api.track_open_signals(candles,"5m")
    assert len(closed)==1
    assert api._MEM_SIGNALS[0]["result"]=="WIN"
    assert api._MEM_SIGNALS[0]["status"]=="CLOSED"


def test_auto_tracker_does_not_expire_unreached_signal(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api._MEM_SIGNALS.clear()
    api._MEM_SIGNALS.append({
        "id":"2","candle_id":"300000","timeframe":"5m","direction":"SHORT",
        "entry":100.0,"stop":103.0,"target":95.0,"status":"CONFIRMED","result":None,
    })
    candles=pd.DataFrame([
        {"open_time":600000,"high":102.0,"low":98.0},
        {"open_time":900000,"high":101.0,"low":97.0},
    ])
    assert api.track_open_signals(candles,"5m")==[]
    assert api._MEM_SIGNALS[0]["status"]=="CONFIRMED"
    assert api._MEM_SIGNALS[0]["result"] is None


def test_same_candle_sl_and_tp_is_recorded_as_conservative_loss(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api._MEM_SIGNALS.clear()
    api._MEM_SIGNALS.append({
        "id":"3","candle_id":"300000","timeframe":"5m","direction":"LONG",
        "entry":100.0,"stop":98.0,"target":104.0,"status":"CONFIRMED","result":None,
    })
    candles=pd.DataFrame([{"open_time":600000,"high":105.0,"low":97.0}])
    api.track_open_signals(candles,"5m")
    assert api._MEM_SIGNALS[0]["result"]=="LOSS"
    assert api._MEM_SIGNALS[0]["result_reason"]=="BOTH_LEVELS_TOUCHED_SAME_CANDLE"


def test_settings_accept_advanced_indicators(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api._MEM_CONFIG.clear()
    saved=api.set_settings({
        "timeframe":"15m","modules":["trend","adx","fibonacci","chart_patterns"],
        "min_score":3,"target_r":2,
    })
    assert "fibonacci" in saved["modules"]
    assert saved["min_score"]==3

def test_generated_candidate_is_tracked_without_manual_confirmation(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api._MEM_SIGNALS.clear()
    api._MEM_SIGNALS.append({
        "id":"4","candle_id":"300000","timeframe":"5m","direction":"SHORT",
        "entry":100.0,"stop":103.0,"target":95.0,"status":"CANDIDATE","result":None,
    })
    candles=pd.DataFrame([{"open_time":600000,"high":104.0,"low":99.0}])
    closed=api.track_open_signals(candles,"5m")
    assert len(closed)==1
    assert api._MEM_SIGNALS[0]["result"]=="LOSS"
    assert api._MEM_SIGNALS[0]["status"]=="CLOSED"
    assert api.list_signals()==[]
    assert api.list_trades()["trades"][0]["result"]=="LOSS"
