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
