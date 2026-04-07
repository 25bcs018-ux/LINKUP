import unittest

from encryption.pipeline import (
    custom_decode_text,
    custom_encode_text,
    transport_decode_text,
    transport_encode_text,
)


class CustomPipelineTests(unittest.TestCase):
    def test_round_trip(self):
        text = "Hello world ✓"

        payload = custom_encode_text(text, mask_seed=123456, strategy_name="twist")

        self.assertEqual(custom_decode_text(payload), text)

    def test_non_pipeline_payload_is_returned_unchanged(self):
        self.assertEqual(custom_decode_text("plain text"), "plain text")

    def test_transport_round_trip(self):
        text = "Transport ✓ hello"

        payload = transport_encode_text(text, mask_seed=98765, strategy_name="shift")

        self.assertEqual(transport_decode_text(payload), text)


if __name__ == "__main__":
    unittest.main()