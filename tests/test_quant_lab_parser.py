import unittest

from quant_lab.nlp import interpret_strategy
from quant_lab.strategy import strategy_from_dict


class NaturalLanguageParserTests(unittest.TestCase):
    def test_long_rules_generate_engine_compatible_inverse_short(self):
        result = interpret_strategy(
            "LONG: comprar cuando el precio esté por encima de EMA 200 "
            "y EMA 50 por encima de EMA 200 y RSI 14 menor que 65.",
            "BTC Trend"
        )
        strategy = strategy_from_dict(result["strategy"])
        self.assertEqual(strategy.name, "BTC Trend")
        self.assertEqual(len(strategy.long_conditions), 3)
        self.assertEqual(len(strategy.short_conditions), 3)
        self.assertTrue(result["derived_opposite"])
        self.assertTrue(result["warnings"])

    def test_explicit_long_and_short_blocks(self):
        result = interpret_strategy(
            "LONG: close > ema_200. SHORT: close < ema_200.",
            "BTC Two Sided"
        )
        strategy = strategy_from_dict(result["strategy"])
        self.assertEqual(strategy.long_conditions[0].operator, ">")
        self.assertEqual(strategy.short_conditions[0].operator, "<")
        self.assertFalse(result["derived_opposite"])

    def test_rsi_and_volume_rules(self):
        result = interpret_strategy(
            "Comprar cuando RSI 14 sea menor que 30 y volumen relativo mayor que 1.2"
        )
        self.assertEqual(result["strategy"]["long_conditions"][0]["feature"], "rsi_14")
        self.assertIn("volume_ratio", [x["feature"] for x in result["strategy"]["long_conditions"]])

    def test_atr_14_rule_is_supported(self):
        result = interpret_strategy("LONG: comprar cuando ATR 14 mayor que 100")
        self.assertEqual(result["strategy"]["long_conditions"][0]["feature"], "atr_14")

    def test_unsupported_ema_period_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Periodo EMA no soportado"):
            interpret_strategy("LONG: precio por encima de EMA 21 y RSI 14 menor que 65")

    def test_unsupported_cross_is_rejected_explicitly(self):
        with self.assertRaisesRegex(ValueError, "cruces de indicadores"):
            interpret_strategy("LONG: cruce EMA 20 con EMA 50")

    def test_supported_rule_does_not_hide_unsupported_clause(self):
        with self.assertRaisesRegex(ValueError, "reglas no soportadas"):
            interpret_strategy("LONG: close > ema_200 y cruce EMA 20 con EMA 50")

    def test_ambiguous_directions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "etiquetas explícitas"):
            interpret_strategy("Comprar cuando close > ema_200 y vender cuando close < ema_200")

    def test_unrecognized_text_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "No se reconocieron reglas"):
            interpret_strategy("LONG: comprar cuando la luna esté llena")


if __name__ == "__main__":
    unittest.main()
