import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import crypto
from encryption.pipeline import CUSTOM_PIPELINE_PREFIX


class CryptoTests(unittest.TestCase):
    def setUp(self):
        # Make tests deterministic w.r.t. key.
        os.environ["SECRET_KEY"] = "unit-test-secret"
        os.environ.pop("CHAT_ENC_KEY", None)

    def test_round_trip(self):
        msg = "hello world ✓"
        token = crypto.encrypt_text(msg)
        self.assertTrue(token.startswith("v3:"))
        self.assertEqual(crypto.decrypt_text(token), msg)

    def test_encrypt_text_uses_custom_pipeline_before_aead(self):
        msg = "pipeline check"
        token = crypto.encrypt_text(msg)

        decrypted_inner = crypto.decrypt_bytes(token).decode("utf-8")

        self.assertTrue(decrypted_inner.startswith(CUSTOM_PIPELINE_PREFIX))
        self.assertEqual(crypto.decrypt_text(token), msg)

    def test_legacy_v2_round_trip_still_decrypts(self):
        msg = "legacy secret"
        token = crypto._encrypt_v2(msg.encode("utf-8"))

        self.assertTrue(token.startswith("v2:"))
        self.assertEqual(crypto.decrypt_text(token), msg)

    def test_legacy_plaintext_passthrough(self):
        self.assertEqual(crypto.decrypt_text("plain"), "plain")

    def test_tamper_detection(self):
        token = crypto.encrypt_text("secret")
        # flip one character in the base64 payload (not the prefix)
        tampered = token[:4] + ("A" if token[4] != "A" else "B") + token[5:]
        with self.assertRaises(crypto.CryptoError):
            crypto.decrypt_text(tampered)

    def test_load_master_key_falls_back_to_persisted_demo_key(self):
        expected_key = crypto.generate_key_b64url()
        with tempfile.TemporaryDirectory() as tmpdir:
            key_file = Path(tmpdir) / ".demo_enc_key"
            key_file.write_text(expected_key, encoding="utf-8")

            with mock.patch.dict(os.environ, {"SECRET_KEY": "wrong-secret"}, clear=False):
                os.environ.pop("CHAT_ENC_KEY", None)
                with mock.patch.object(crypto, "_fallback_key_file", return_value=key_file):
                    loaded = crypto._load_master_key()

        self.assertEqual(loaded, crypto._b64url_decode(expected_key))


if __name__ == "__main__":
    unittest.main()
