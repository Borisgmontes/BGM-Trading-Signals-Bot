import web_worker as worker
from web_worker import RADAR_MODULES, radar_module_labels


def test_radar_module_labels_maps_ids_to_human_readable_names():
    labels = radar_module_labels(["trend", "rsi", "macd"])
    assert labels == ["Tendencia EMA", "RSI", "MACD"]


def test_radar_module_labels_keeps_unknown_ids_without_crashing():
    assert radar_module_labels(["trend", "future_module"]) == [
        "Tendencia EMA", "future_module"
    ]


def test_every_configured_radar_module_has_a_label():
    ids = [module_id for _, module_id in RADAR_MODULES]
    labels = radar_module_labels(ids)
    assert len(labels) == len(ids)
    assert all(labels)


def _set_healthy_dependencies(monkeypatch):
    monkeypatch.setitem(worker.ready, "scanner_started", True)
    monkeypatch.setitem(worker.ready, "database_configured", True)
    monkeypatch.setitem(worker.ready, "telegram_configured", True)
    monkeypatch.setattr(worker, "db_ready", True)


def test_health_is_200_only_when_dependencies_and_scan_are_healthy(monkeypatch):
    _set_healthy_dependencies(monkeypatch)
    status, payload = worker.health_snapshot(
        {"last_success_at": "2026-11-23T15:00:00+00:00", "last_error": None},
        now=1795446300,
    )
    assert status == 200
    assert payload["status"] == "healthy"


def test_health_is_503_when_database_is_not_ready(monkeypatch):
    _set_healthy_dependencies(monkeypatch)
    monkeypatch.setattr(worker, "db_ready", False)
    status, payload = worker.health_snapshot(
        {"last_success_at": "2026-11-23T15:00:00+00:00", "last_error": None},
        now=1795446300,
    )
    assert status == 503
    assert payload["checks"]["database_ready"] is False


def test_health_is_503_when_telegram_is_not_configured(monkeypatch):
    _set_healthy_dependencies(monkeypatch)
    monkeypatch.setitem(worker.ready, "telegram_configured", False)
    status, payload = worker.health_snapshot(
        {"last_success_at": "2026-11-23T15:00:00+00:00", "last_error": None},
        now=1795446300,
    )
    assert status == 503
    assert payload["checks"]["telegram_configured"] is False


def test_health_is_503_when_last_scan_is_stale_or_failed(monkeypatch):
    _set_healthy_dependencies(monkeypatch)
    stale_status, _ = worker.health_snapshot(
        {"last_success_at": "2026-11-23T14:00:00+00:00", "last_error": None},
        now=1795446300,
    )
    failed_status, _ = worker.health_snapshot(
        {"last_success_at": "2026-11-23T15:00:00+00:00", "last_error": "network error"},
        now=1795446300,
    )
    assert stale_status == 503
    assert failed_status == 503
