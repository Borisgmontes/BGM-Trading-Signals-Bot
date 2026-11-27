import json
from io import BytesIO

import pandas as pd
import pytest

import dashboard_api as api


def reset_memory(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api._MEM_CONFIG.clear()
    api._MEM_CONFIG.update(api.DEFAULT)
    api._MEM_SIGNALS.clear()
    api._MEM_SUBSCRIPTIONS.clear()
    api._MEM_STATS_EPOCH.clear()
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
        "strategy_hash": api.strategy_hash(api.get_settings()),
        "config_snapshot": api.get_settings(), "stats_epoch": 0,
        "status": "CANDIDATE", "created_at": None,
    })
    assert api.update_signal("1", "CONFIRMED") is True
    assert api.list_signals() == []
    assert api.list_trades()["trades"][0]["status"] == "CONFIRMED"
    assert api.update_signal("1", "DISCARDED") is False


def _set_valid_vapid_pair(monkeypatch):
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    private = ec.generate_private_key(ec.SECP256R1())
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = private.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public_key = base64.urlsafe_b64encode(public_raw).rstrip(b"=").decode("ascii")
    monkeypatch.setattr(api, "VAPID_PRIVATE", private_pem.decode("ascii"))
    monkeypatch.setattr(api, "VAPID_PUBLIC", public_key)
    return private


def test_vapid_pem_is_loaded_and_public_key_pair_is_verified(monkeypatch):
    expected_private = _set_valid_vapid_pair(monkeypatch)

    loaded = api._load_vapid_key()

    assert loaded.private_key.private_numbers().private_value == (
        expected_private.private_numbers().private_value
    )


def test_vapid_rejects_mismatched_public_and_private_keys(monkeypatch):
    _set_valid_vapid_pair(monkeypatch)
    monkeypatch.setattr(api, "VAPID_PUBLIC", "not-the-matching-public-key")

    try:
        api._load_vapid_key()
    except RuntimeError as exc:
        assert "VAPID" in str(exc)
    else:
        raise AssertionError("Mismatched VAPID key pair must be rejected")


def test_vapid_rejects_malformed_private_key(monkeypatch):
    monkeypatch.setattr(api, "VAPID_PRIVATE", "this-is-not-a-valid-private-key")
    monkeypatch.setattr(api, "VAPID_PUBLIC", "a-valid-looking-public-key")

    try:
        api._load_vapid_key()
    except RuntimeError as exc:
        assert "Clave VAPID inválida" in str(exc)
    else:
        raise AssertionError("Malformed VAPID private key must be rejected")


def test_strategy_hash_is_stable_and_changes_with_configuration(monkeypatch):
    reset_memory(monkeypatch)
    first = api.strategy_hash(api.get_settings())
    changed = dict(api.get_settings())
    changed["modules"] = ["trend", "rsi"]
    assert api.strategy_hash(changed) != first
    assert api.strategy_hash(dict(api.get_settings())) == first


def test_strategy_statistics_are_separated_by_configuration(monkeypatch):
    reset_memory(monkeypatch)
    cfg = api.get_settings()
    current_hash = api.strategy_hash(cfg)
    api._MEM_SIGNALS.extend([
        {"id": "1", "status": "CLOSED", "result": "WIN", "entry": 100,
         "stop": 99, "target": 102, "strategy_hash": current_hash, "stats_epoch": 0},
        {"id": "2", "status": "CLOSED", "result": "LOSS", "entry": 100,
         "stop": 99, "target": 102, "strategy_hash": "other-config", "stats_epoch": 0},
    ])
    stats = api.list_trades()
    assert stats["stats"]["total"] == 1
    assert stats["stats"]["wins"] == 1
    assert len(stats["strategies"]) == 2


def test_manual_stats_reset_preserves_old_trades(monkeypatch):
    reset_memory(monkeypatch)
    cfg_hash = api.strategy_hash(api.get_settings())
    api._MEM_SIGNALS.append({
        "id": "1", "status": "CLOSED", "result": "WIN", "entry": 100,
        "stop": 99, "target": 102, "strategy_hash": cfg_hash, "stats_epoch": 0,
    })
    api._MEM_STATS_EPOCH[cfg_hash] = 1
    stats = api.list_trades()
    assert stats["stats"]["total"] == 0
    assert stats["strategies"][0]["stats"]["total"] == 1
    assert len(api._MEM_SIGNALS) == 1



def test_scan_status_isolated_by_dashboard_tenant():
    with api._tenant_scope("tenant-a"):
        api._SCAN_STATUS["last_price"] = 123.45
        a = api.scan_status()
    with api._tenant_scope("tenant-b"):
        b = api.scan_status()
        api._SCAN_STATUS["last_price"] = 987.65
    with api._tenant_scope("tenant-a"):
        a_after = api.scan_status()
    assert a["last_price"] == 123.45
    assert b["last_price"] is None
    assert a_after["last_price"] == 123.45



def test_system_scan_status_aggregates_without_exposing_market_prices():
    api._SCAN_STATUS_BY_TENANT.clear()
    with api._tenant_scope("tenant-a"):
        api._SCAN_STATUS.update({"last_success_at":"2026-11-27T07:00:00+00:00","last_attempt_at":"2026-11-27T07:00:01+00:00","last_price":123.45,"scan_count":2,"success_count":2})
    with api._tenant_scope("tenant-b"):
        api._SCAN_STATUS.update({"last_success_at":"2026-11-27T07:01:00+00:00","last_attempt_at":"2026-11-27T07:01:01+00:00","last_price":987.65,"scan_count":3,"success_count":2})
    status = api.system_scan_status()
    assert status["last_success_at"] == "2026-11-27T07:01:00+00:00"
    assert status["scan_count"] == 5
    assert status["success_count"] == 4
    assert "last_price" not in status



def test_market_freshness_rejects_stale_yahoo_gold_proxy():
    now = 1_800_000_000
    frame = pd.DataFrame([{
        "open_time": (now - 2 * 60 * 60) * 1000,
        "close_time": (now - 2 * 60 * 60) * 1000,
        "close": 3500.0,
    }])
    with pytest.raises(ValueError, match="Datos atrasados"):
        api._validate_market_freshness(frame, "XAUUSD", "5m", now=now)


def test_market_freshness_accepts_recent_binance_candle():
    now = 1_800_000_000
    frame = pd.DataFrame([{
        "open_time": (now - 5 * 60) * 1000,
        "close_time": (now - 1) * 1000,
        "close": 60000.0,
    }])
    result = api._validate_market_freshness(frame, "BTCUSDT", "5m", now=now)
    assert result["source"] == "Binance.US spot"


class _FakeHandler:
    def __init__(self, body):
        self.path = "/api/dashboard/login"
        self.command = "POST"
        self.headers = {"Content-Length": str(len(body))}
        self.rfile = BytesIO(body)
        self.wfile = BytesIO()
        self.status = None

    def send_response(self, status):
        self.status = status

    def send_header(self, *_args):
        pass

    def end_headers(self):
        pass


def test_dashboard_login_route_returns_a_session_for_valid_pin(monkeypatch):
    monkeypatch.setattr(api, "_user_for_pin", lambda pin: "tenant-1" if pin == "12345678" else None)
    monkeypatch.setattr(api, "_create_session", lambda user_id: "session-token" if user_id == "tenant-1" else None)
    body = json.dumps({"pin": "12345678"}).encode()
    handler = _FakeHandler(body)

    assert api.handle(handler) is True
    assert handler.status == 200
    assert json.loads(handler.wfile.getvalue()) == {"ok": True, "token": "session-token"}


def test_dashboard_login_route_rejects_invalid_pin(monkeypatch):
    monkeypatch.setattr(api, "_user_for_pin", lambda _pin: None)
    handler = _FakeHandler(json.dumps({"pin": "00000000"}).encode())

    assert api.handle(handler) is True
    assert handler.status == 401
    assert json.loads(handler.wfile.getvalue())["error"] == "PIN incorrecto o no habilitado."


class _FakeCursor:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def fetchone(self):
        return self.row

    def fetchall(self):
        return self.rows


class _FakePinConnection:
    def __init__(self):
        self.users = [
            {"user_id": "current", "pin_lookup_hash": "allowed-hash", "active": True},
            {"user_id": "stale", "pin_lookup_hash": "old-hash", "active": True},
            {"user_id": "legacy", "pin_lookup_hash": None, "pin_salt": "salt", "pin_hash": "not-match", "active": True},
        ]
        self.sessions = [{"user_id": "current"}, {"user_id": "stale"}, {"user_id": "legacy"}]

    def execute(self, query, params=()):
        if "SELECT user_id,pin_salt,pin_hash FROM bgm_dashboard_users" in query:
            rows = [
                {k: v for k, v in user.items() if k in ("user_id", "pin_salt", "pin_hash")}
                for user in self.users if user["active"] and user.get("pin_lookup_hash") is None
            ]
            return _FakeCursor(rows=rows)
        if "SELECT user_id FROM bgm_dashboard_users WHERE pin_lookup_hash" in query:
            row = next(({"user_id": user["user_id"]} for user in self.users
                        if user["active"] and user.get("pin_lookup_hash") == params[0]), None)
            return _FakeCursor(row=row)
        if query.startswith("INSERT INTO bgm_dashboard_users"):
            user_id, _salt, _pin_hash, lookup_hash = params
            self.users.append({"user_id": user_id, "pin_lookup_hash": lookup_hash, "active": True})
            return _FakeCursor()
        if query.startswith("UPDATE bgm_dashboard_users SET pin_lookup_hash"):
            lookup_hash, user_id = params
            for user in self.users:
                if user["user_id"] == user_id:
                    user["pin_lookup_hash"] = lookup_hash
            return _FakeCursor()
        if query.startswith("UPDATE bgm_dashboard_users SET active=false"):
            allowed = set(params[0])
            for user in self.users:
                if user["active"] and user.get("pin_lookup_hash") not in allowed:
                    user["active"] = False
            return _FakeCursor()
        if query.startswith("DELETE FROM bgm_dashboard_sessions"):
            inactive = {u["user_id"] for u in self.users if not u["active"]}
            self.sessions = [s for s in self.sessions if s["user_id"] not in inactive]
            return _FakeCursor()
        raise AssertionError("Consulta inesperada en prueba de PIN provisioning")


def test_pin_provisioning_disables_removed_accounts_and_sessions(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PINS", "12345678")
    monkeypatch.setattr(api, "_pin_lookup_hash", lambda _pin: "allowed-hash")
    monkeypatch.setattr(api, "_pin_digest", lambda _pin, _salt: "digest")
    conn = _FakePinConnection()

    api._provision_pins(conn)

    active = {u["user_id"] for u in conn.users if u["active"]}
    assert active == {"current"}
    assert conn.sessions == [{"user_id": "current"}]
