"""Constrained Spanish/English natural-language parser for the BTC strategy schema.

Only explicit, auditable comparisons are converted into rules. Unsupported constructs
are reported instead of being silently guessed.
"""
from __future__ import annotations

import re
import unicodedata

from .strategy import ALLOWED_FEATURES, Condition, Strategy

_OPERATOR = r"(?:por\s+encima\s+de|mayor\s+que|above|greater\s+than|>=|>|por\s+debajo\s+de|menor\s+que|below|less\s+than|<=|<)"
_EMA = r"(?:10|20|50|100|200)"
_FEATURE = r"(?:close|ema_10|ema_20|ema_50|ema_100|ema_200|rsi_14|atr_14|bb_upper|bb_lower|volume_ratio|macd_hist)"


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return re.sub(r"(?<=\d),(?=\d)", ".", value)


def _operator(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip().lower())
    if value in {">", ">=", "por encima de", "mayor que", "above", "greater than"}:
        return value if value == ">=" else ">"
    if value in {"<", "<=", "por debajo de", "menor que", "below", "less than"}:
        return value if value == "<=" else "<"
    raise ValueError(f"Operador no soportado: {value}")


def _value(value: str):
    token = value.strip().lower()
    if token in ALLOWED_FEATURES:
        return token
    try:
        number = float(token)
    except ValueError as exc:
        raise ValueError(f"Valor no reconocido: {value}") from exc
    if not (number == number and abs(number) != float("inf")):
        raise ValueError("Los valores numéricos deben ser finitos.")
    return number


def _parse_conditions(section: str) -> list[Condition]:
    found: list[Condition] = []

    def add(feature: str, operator: str, value):
        parsed_value = value if isinstance(value, (int, float)) else _value(str(value))
        rule = Condition(feature, _operator(operator), parsed_value)
        if rule not in found:
            found.append(rule)

    patterns = [
        (rf"\bema\s*({_EMA})\s*({_OPERATOR})\s*ema\s*({_EMA})\b",
         lambda m: ("ema_" + m.group(1), m.group(2), "ema_" + m.group(3))),
        (rf"\b(?:precio|close|cierre)\s*(?:(?:esta|este|se encuentre|situado|situada)\s*)?({_OPERATOR})\s*ema\s*({_EMA})\b",
         lambda m: ("close", m.group(1), "ema_" + m.group(2))),
        (rf"\brsi(?:\s*14)?\s*(?:(?:sea|esta|este|se encuentre)\s*)?({_OPERATOR})\s*(\d{{1,3}}(?:\.\d+)?)\b",
         lambda m: ("rsi_14", m.group(1), float(m.group(2)))),
        (rf"\batr(?:\s*14)?\s*(?:(?:sea|esta|este|se encuentre)\s*)?({_OPERATOR})\s*(\d+(?:\.\d+)?)\b",
         lambda m: ("atr_14", m.group(1), float(m.group(2)))),
        (rf"\b(?:volumen(?:\s+relativo)?|volume\s+ratio)\s*(?:(?:sea|esta|este)\s*)?({_OPERATOR})\s*(\d+(?:\.\d+)?)\b",
         lambda m: ("volume_ratio", m.group(1), float(m.group(2)))),
        (rf"\b({_FEATURE})\s*(>=|<=|>|<)\s*({_FEATURE}|-?\d+(?:\.\d+)?)\b",
         lambda m: (m.group(1), m.group(2), m.group(3))),
    ]
    for pattern, build in patterns:
        for match in re.finditer(pattern, section):
            feature, op, value = build(match)
            add(feature, op, value)

    phrases = [
        (r"\bmacd(?:\s+hist(?:ograma|ogram))?\s+(?:es\s+)?positivo\b", "macd_hist", ">", 0),
        (r"\bmacd(?:\s+hist(?:ograma|ogram))?\s+(?:es\s+)?negativo\b", "macd_hist", "<", 0),
        (r"\b(?:precio|close|cierre)\s+(?:por\s+encima\s+de|above)\s+(?:la\s+)?(?:banda\s+superior|upper\s+band)\b", "close", ">", "bb_upper"),
        (r"\b(?:precio|close|cierre)\s+(?:por\s+debajo\s+de|below)\s+(?:la\s+)?(?:banda\s+inferior|lower\s+band)\b", "close", "<", "bb_lower"),
    ]
    for pattern, feature, op, value in phrases:
        if re.search(pattern, section):
            add(feature, op, value)
    return found


def _invert(rules: list[Condition]) -> list[Condition]:
    inverse = {">": "<", "<": ">", ">=": "<=", "<=": ">="}
    return [Condition(rule.feature, inverse[rule.operator], rule.value) for rule in rules]


def _describe(rules: list[Condition]) -> list[str]:
    return [f"{rule.feature} {rule.operator} {rule.value}" for rule in rules]


def interpret_strategy(description: str, name: str | None = None) -> dict:
    """Return an engine-compatible strategy plus explicit parser diagnostics."""
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Escribe una descripción de estrategia antes de interpretarla.")

    text = _normalize(description)
    unsupported = [
        (r"\b(cruce|cruza|crossover|crosses)\b", "Los cruces de indicadores son eventos; esta versión solo interpreta comparaciones de valores."),
        (r"\b(vwap|fibonacci|choch|bos|estocastico|stochastic|adx|supertrend|ichimoku|obv|cci|mfi)\b", "Se detectaron indicadores o conceptos que este parser todavía no soporta."),
        (r"\bema\s*(?!(?:10|20|50|100|200)\b)\d+\b", "Periodo EMA no soportado; utiliza EMA 10, 20, 50, 100 o 200."),
        (r"\brsi\s*(?!14\b)\d+\b", "Periodo RSI no soportado; esta versión utiliza RSI 14."),
        (r"\batr\s*(?!14\b)\d+\b", "Periodo ATR no soportado; esta versión utiliza ATR 14."),
    ]
    unsupported_detected = [message for pattern, message in unsupported if re.search(pattern, text)]
    labels = list(re.finditer(r"\b(long|short)\s*[:\-]", text))
    long_rules: list[Condition] = []
    short_rules: list[Condition] = []
    warnings: list[str] = []
    derived_opposite = False

    if labels:
        sections: dict[str, str] = {}
        for index, match in enumerate(labels):
            end = labels[index + 1].start() if index + 1 < len(labels) else len(text)
            sections[match.group(1)] = sections.get(match.group(1), "") + " " + text[match.end():end]
        if "long" in sections:
            long_rules = _parse_conditions(sections["long"])
        if "short" in sections:
            short_rules = _parse_conditions(sections["short"])
        if not long_rules and not short_rules:
            detail = " ".join(unsupported_detected)
            raise ValueError(detail or "No se reconocieron reglas compatibles en los bloques LONG/SHORT.")
        if "long" in sections and not long_rules:
            raise ValueError("El bloque LONG no contiene reglas compatibles.")
        if "short" in sections and not short_rules:
            raise ValueError("El bloque SHORT no contiene reglas compatibles.")
    else:
        has_long = bool(re.search(r"\b(long|largo|comprar|compra|buy)\b", text))
        has_short = bool(re.search(r"\b(short|corto|vender|venta|sell)\b", text))
        if has_long and has_short:
            raise ValueError("Separa las reglas con etiquetas explícitas «LONG: ... SHORT: ...» para evitar ambigüedad.")
        if not has_long and not has_short:
            raise ValueError("Indica si la estrategia opera LONG o SHORT.")
        rules = _parse_conditions(text)
        if not rules:
            detail = " ".join(unsupported_detected)
            raise ValueError(detail or "No se reconocieron reglas. Usa comparaciones de precio/EMA, EMA/EMA, RSI, volumen relativo, MACD o bandas Bollinger.")
        if has_short:
            short_rules = rules
        else:
            long_rules = rules

    if long_rules and not short_rules:
        short_rules = _invert(long_rules)
        derived_opposite = True
        warnings.append("SHORT se generó invirtiendo las condiciones LONG; revisa que esa contraparte tenga sentido para tu estrategia.")
    elif short_rules and not long_rules:
        long_rules = _invert(short_rules)
        derived_opposite = True
        warnings.append("LONG se generó invirtiendo las condiciones SHORT; revisa que esa contraparte tenga sentido para tu estrategia.")

    if unsupported_detected:
        raise ValueError("No se puede interpretar esta estrategia porque contiene reglas no soportadas: " + " ".join(unsupported_detected))

    strategy_name = (name or "").strip() or description.strip().splitlines()[0][:60] or "BTC Strategy"
    strategy = Strategy(strategy_name, tuple(long_rules), tuple(short_rules))
    return {
        "strategy": strategy.to_dict(),
        "recognized": {"long": _describe(long_rules), "short": _describe(short_rules)},
        "derived_opposite": derived_opposite,
        "warnings": warnings,
        "parser": "constrained-spanish-english-v1",
    }
