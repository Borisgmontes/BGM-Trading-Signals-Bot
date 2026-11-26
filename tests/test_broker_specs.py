import pytest

from broker_specs import get_instrument_spec, swap_cost_usd, validate_volume


def test_xauusd_contract_and_volume_spec():
    spec = get_instrument_spec("XAUUSD")
    assert spec["contract_size"] == 100.0
    assert spec["volume_min"] == 0.01
    assert spec["volume_max"] == 1000.0
    assert spec["volume_step"] == 0.01


def test_xauusd_swap_points_convert_to_usd():
    # 600 points * 0.001 * 100 oz * 0.01 lot = $0.60 per rollover.
    assert swap_cost_usd("XAUUSD", 0.01, 0, "LONG") == pytest.approx(-0.60)
    assert swap_cost_usd("XAUUSD", 0.01, 0, "SHORT") == pytest.approx(-0.15)


def test_xauusd_wednesday_swap_is_triple():
    assert swap_cost_usd("XAUUSD", 0.01, 2, "LONG") == pytest.approx(-1.80)


def test_volume_step_is_enforced():
    assert validate_volume("XAUUSD", 0.03) == pytest.approx(0.03)
    with pytest.raises(ValueError):
        validate_volume("XAUUSD", 0.015)


def test_btc_swap_is_not_assumed():
    with pytest.raises(ValueError, match="no verificado"):
        swap_cost_usd("BTCUSD", 0.01, 0, "LONG")
