import unittest

from encryption.masking import dmask, identify_masking_strategy, unmask


class MaskingTests(unittest.TestCase):
    def test_round_trip(self):
        original = [[7128, 7382, 9999], [2946, 4668, 5182, 5037, 5182, 9999]]

        masked = dmask(original, mask_seed=123456)

        self.assertIn(masked["strategy"], {"xor", "shift", "twist"})
        self.assertEqual(unmask(masked), original)
        self.assertNotEqual(masked["masked_data"], original)

    def test_generates_seed_when_missing(self):
        masked = dmask([[1, 2, 3]])

        self.assertIsInstance(masked["mask_seed"], int)
        self.assertGreater(masked["mask_seed"], 0)
        self.assertEqual(unmask(masked), [[1, 2, 3]])

    def test_allows_explicit_strategy_override(self):
        original = [[10, 20, 30]]

        masked = dmask(original, mask_seed=999, strategy_name="shift")
        strategy_name, _ = identify_masking_strategy(masked)

        self.assertEqual(strategy_name, "shift")
        self.assertEqual(unmask(masked), original)

    def test_rejects_non_integer_tokens(self):
        with self.assertRaises(TypeError):
            dmask([[1, "2", 3]], mask_seed=9)

    def test_rejects_unknown_strategy_in_payload(self):
        with self.assertRaises(ValueError):
            unmask({"strategy": "missing", "mask_seed": 4, "masked_data": [[1, 2]]})


if __name__ == "__main__":
    unittest.main()