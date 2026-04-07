import unittest

from encryption.symbolisation import desymboliser, symboliser


class SymbolisationTests(unittest.TestCase):
    def test_round_trip_matrix(self):
        masked_data = [[0, 1, 20, 21, 42], [9999, 123456]]

        payload = symboliser(masked_data)

        self.assertIn("symbolised_data", payload)
        self.assertEqual(desymboliser(payload), masked_data)

    def test_preserves_masking_metadata(self):
        masked_payload = {
            "version": 1,
            "strategy": "shift",
            "mask_seed": 12345,
            "masked_data": [[101, 202, 303]],
        }

        symbol_payload = symboliser(masked_payload)
        restored = desymboliser(symbol_payload)

        self.assertEqual(restored["version"], 1)
        self.assertEqual(restored["strategy"], "shift")
        self.assertEqual(restored["mask_seed"], 12345)
        self.assertEqual(restored["masked_data"], [[101, 202, 303]])

    def test_supports_negative_values(self):
        masked_data = [[-1, -42, 0, 42]]

        self.assertEqual(desymboliser(symboliser(masked_data)), masked_data)

    def test_rejects_unknown_strategy(self):
        with self.assertRaises(ValueError):
            desymboliser({"symbol_strategy": "unknown", "symbolised_data": [["!"]]})

    def test_rejects_non_integer_input(self):
        with self.assertRaises(TypeError):
            symboliser([[1, "2", 3]])


if __name__ == "__main__":
    unittest.main()