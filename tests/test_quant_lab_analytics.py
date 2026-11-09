import pytest
from quant_lab import api

def test_analytics_event_requires_storage(monkeypatch):
    monkeypatch.setattr(api.analytics_store, "is_configured", lambda: False)
    response = api.app.test_client().post("/api/analytics/event", json={
        "event_type": "page_view", "visitor_id": "v1", "session_id": "s1", "page_path": "/"
    })
    assert response.status_code == 503

def test_analytics_report_requires_admin_token(monkeypatch):
    monkeypatch.setenv("QUANT_ADMIN_TOKEN", "test-secret")
    response = api.app.test_client().get("/api/analytics/report")
    assert response.status_code == 401

def test_analytics_report_returns_aggregate(monkeypatch):
    monkeypatch.setenv("QUANT_ADMIN_TOKEN", "test-secret")
    monkeypatch.setattr(api.analytics_store, "is_configured", lambda: True)
    monkeypatch.setattr(api.analytics_store, "daily_report", lambda days: {
        "period_days": days, "unique_visitors": 4, "page_views": 9, "sessions": 5,
        "strategies_saved": 2, "interpretations": 3, "backtests": 2, "client_errors": 0,
        "top_pages": [], "event_breakdown": [], "generated_at": "2026-11-08T00:00:00+00:00",
        "storage": "postgresql"
    })
    response = api.app.test_client().get("/api/analytics/report?days=7",
        headers={"Authorization": "Bearer test-secret"})
    assert response.status_code == 200
    assert response.get_json()["unique_visitors"] == 4
    assert response.get_json()["period_days"] == 7

def test_analytics_event_stores_anonymous_event(monkeypatch):
    monkeypatch.setattr(api.analytics_store, "is_configured", lambda: True)
    captured = {}
    monkeypatch.setattr(api.analytics_store, "record_event", lambda payload: captured.update(payload))
    response = api.app.test_client().post("/api/analytics/event", json={
        "event_type": "page_view", "visitor_id": "anonymous-id", "session_id": "session-id",
        "page_path": "/", "metadata": {}
    })
    assert response.status_code == 202
    assert captured["visitor_id"] == "anonymous-id"
