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
