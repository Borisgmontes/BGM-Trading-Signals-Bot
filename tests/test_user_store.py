import user_store


def test_user_strategies_are_isolated_and_deduplicated(monkeypatch):
    monkeypatch.setattr(user_store, "DATABASE_URL", "")
    monkeypatch.setattr(user_store, "_MEM_USERS", {})
    monkeypatch.setattr(user_store, "_MEM_STRATEGIES", {})
    monkeypatch.setattr(user_store, "_MEM_SENT", set())
    monkeypatch.setattr(user_store, "_NEXT_ID", 1)

    user_store.upsert_user(101, 1001, "alice")
    user_store.upsert_user(202, 2002, "bob")
    alice_id = user_store.create_strategy(101, "BTC RADAR", {"mode": "radar"})
    bob_id = user_store.create_strategy(202, "BTC RADAR", {"mode": "radar"})

    assert len(user_store.list_strategies(101)) == 1
    assert len(user_store.list_strategies(202)) == 1
    assert user_store.claim_signal(alice_id, "candle-1") is True
    assert user_store.claim_signal(alice_id, "candle-1") is False
    assert user_store.claim_signal(bob_id, "candle-1") is True
