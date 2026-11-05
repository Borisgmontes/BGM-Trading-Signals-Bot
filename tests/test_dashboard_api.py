import dashboard_api as api


def reset_memory(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api._MEM_CONFIG.clear()
    api._MEM_CONFIG.update(api.DEFAULT)
    api._MEM_SIGNALS.clear()
    api._MEM_SUBSCRIPTIONS.clear()
    api._MEM_NEXT_ID = 1


def test_dashboard_settings_work_without_database(monkeypatch):
    reset_memory(monkeypatch)
    saved = api.set_settings({
        "timeframe": "15m",
        "modules": ["trend", "rsi", "volume"],
        "min_score": 2,
        "target_r": 1.5,
    })
    assert saved["timeframe"] == "15m"
    assert api.get_settings()["min_score"] == 2


def test_dashboard_rejects_confirmation_count_above_modules(monkeypatch):
    reset_memory(monkeypatch)
    try:
        api.set_settings({
            "timeframe": "5m",
            "modules": ["trend"],
            "min_score": 2,
            "target_r": 2,
        })
    except ValueError:
        return
    raise AssertionError("Invalid minimum confirmations should be rejected")


def test_dashboard_signal_can_be_confirmed_in_memory(monkeypatch):
    reset_memory(monkeypatch)
    api._MEM_SIGNALS.append({
        "id": "1", "candle_id": "c1", "timeframe": "5m",
        "direction": "LONG", "entry": 100.0, "stop": 98.0,
        "target": 104.0, "score": 3, "maximum": 8,
        "probability": None, "confirmations": [],
        "status": "CANDIDATE", "created_at": None,
    })
    assert api.update_signal("1", "CONFIRMED") is True
    assert api.list_signals()[0]["status"] == "CONFIRMED"
    assert api.update_signal("1", "DISCARDED") is False
