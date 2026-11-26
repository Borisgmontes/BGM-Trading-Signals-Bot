"""Verified broker contract metadata used by BGM backtests.

Values below are transcribed from the user's Weltrade Pro MT5 specifications.
Swap conversion assumes MT5 swap mode is points:
USD = swap_points * point_size * contract_size * lots.
Floating spread must be supplied from historical Bid/Ask data; it is never
silently treated as zero.
"""

WELTRADE_PRO = {
    "XAUUSD": {
        "contract_size": 100.0,
        "digits": 3,
        "point_size": 0.001,
        "volume_min": 0.01,
        "volume_max": 1000.0,
        "volume_step": 0.01,
        "spread_mode": "floating",
        "commission_usd_per_lot_per_side": 0.0,
        "swap_mode": "points",
        "swap_long_points": -600.0,
        "swap_short_points": -150.0,
        # MT5 weekday numbering: Monday=0 ... Friday=4.
        "swap_multipliers": {0: 1, 1: 1, 2: 3, 3: 1, 4: 1},
        "margin_currency": "USD",
        "profit_currency": "USD",
    },
    "BTCUSD": {
        "contract_size": 1.0,
        "spread_mode": "floating",
        "commission_usd_per_lot_per_side": 0.0,
        "swap_mode": "unverified",
        "swap_long_points": None,
        "swap_short_points": None,
        "volume_min": 0.01,
    },
}


def get_instrument_spec(symbol, broker="weltrade_pro"):
    """Return a defensive copy of a known instrument specification."""
    if broker.lower() != "weltrade_pro":
        raise ValueError("Broker no soportado.")
    try:
        return dict(WELTRADE_PRO[symbol.upper()])
    except KeyError as exc:
        raise ValueError(f"No existe una ficha verificada para {symbol}.") from exc


def validate_volume(symbol, lots, broker="weltrade_pro"):
    """Validate volume against the broker's published minimum/step/maximum."""
    spec = get_instrument_spec(symbol, broker)
    lots = float(lots)
    minimum = float(spec["volume_min"])
    maximum = float(spec.get("volume_max", float("inf")))
    step = float(spec.get("volume_step", minimum))
    if lots < minimum or lots > maximum:
        raise ValueError(f"Volumen fuera de rango: {minimum}–{maximum} lotes.")
    steps = (lots - minimum) / step
    if abs(steps - round(steps)) > 1e-8:
        raise ValueError(f"El volumen debe avanzar en pasos de {step} lotes.")
    return lots


def swap_cost_usd(symbol, lots, weekday, direction, broker="weltrade_pro"):
    """Return the signed overnight swap in USD for one rollover.

    Negative values are costs. weekday uses Monday=0 ... Sunday=6.
    Wednesday's XAUUSD multiplier is 3, per the supplied MT5 specification.
    """
    spec = get_instrument_spec(symbol, broker)
    validate_volume(symbol, lots, broker)
    if weekday not in range(7):
        raise ValueError("weekday debe estar entre 0 (lunes) y 6 (domingo).")
    side = direction.upper()
    if side not in ("LONG", "SHORT"):
        raise ValueError("direction debe ser LONG o SHORT.")
    if spec.get("swap_mode") != "points":
        raise ValueError(f"Swap no verificado para {symbol}.")
    points = spec["swap_long_points"] if side == "LONG" else spec["swap_short_points"]
    multiplier = spec["swap_multipliers"].get(weekday, 0)
    return float(points) * float(spec["point_size"]) * float(spec["contract_size"]) * float(lots) * multiplier
