import argparse
import unittest

from quant_lab.cli import resolve_options


class CliJsonConfigTests(unittest.TestCase):
    def test_json_values_are_used_when_flags_are_omitted(self):
        args = argparse.Namespace(
            timeframe=None, candles=None, fee_bps=None,
            slippage_bps=None, initial_equity=None
        )
        payload = {
            "timeframe": "15m", "candles": 2500, "fee_bps": 7,
            "slippage_bps": 3, "initial_equity": 1250
        }
        self.assertEqual(resolve_options(args, payload), {
            "timeframe": "15m", "candles": 2500, "fee_bps": 7.0,
            "slippage_bps": 3.0, "initial_equity": 1250.0
        })

    def test_command_line_flags_override_json(self):
        args = argparse.Namespace(
            timeframe="1h", candles=3000, fee_bps=8.0,
            slippage_bps=4.0, initial_equity=2000.0
        )
        payload = {"timeframe": "5m", "candles": 500, "fee_bps": 1,
                   "slippage_bps": 1, "initial_equity": 100}
        self.assertEqual(resolve_options(args, payload), {
            "timeframe": "1h", "candles": 3000, "fee_bps": 8.0,
            "slippage_bps": 4.0, "initial_equity": 2000.0
        })


if __name__ == "__main__":
    unittest.main()
