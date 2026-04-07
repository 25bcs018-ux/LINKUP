import os
import tempfile
import unittest


os.environ.setdefault("LINKUP_ENV", "development")

_tmp_db = tempfile.NamedTemporaryFile(prefix="linkup_test_transport_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["LINKUP_CREATE_TABLES"] = "1"

from werkzeug.security import generate_password_hash

from app import app, db, User, ContactRequest, Message, MessageDeletion, MessageStar, MessagePin
from encryption.pipeline import transport_decode_text, transport_encode_text


class MessageTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        except Exception:
            pass

    def setUp(self):
        self.client = app.test_client()
        self.bob_client = app.test_client()
        with app.app_context():
            MessageDeletion.query.delete()
            MessageStar.query.delete()
            MessagePin.query.delete()
            Message.query.delete()
            ContactRequest.query.delete()
            User.query.delete()
            db.session.commit()

            alice = User(
                username="alice",
                email="alice@example.com",
                password=generate_password_hash("pw"),
                email_verified=True,
            )
            bob = User(
                username="bob",
                email="bob@example.com",
                password=generate_password_hash("pw"),
                email_verified=True,
            )
            db.session.add(alice)
            db.session.add(bob)
            db.session.commit()

            db.session.add(ContactRequest(requester_id=alice.id, addressee_id=bob.id, status="accepted"))
            db.session.commit()

            self.alice_id = int(alice.id)
            self.bob_id = int(bob.id)

        with self.client.session_transaction() as sess:
            sess["user_id"] = self.alice_id
            sess["username"] = "alice"

        with self.bob_client.session_transaction() as sess:
            sess["user_id"] = self.bob_id
            sess["username"] = "bob"

    def test_message_api_accepts_and_returns_transport_payloads(self):
        outgoing = "hello over transport ✓"

        send_resp = self.client.post(
            "/api/messages/bob",
            json={"content_transport": transport_encode_text(outgoing, mask_seed=123456, strategy_name="twist")},
        )
        self.assertEqual(send_resp.status_code, 200)
        self.assertEqual(send_resp.json.get("ok"), True)

        read_resp = self.client.get("/api/messages/bob")
        self.assertEqual(read_resp.status_code, 200)
        self.assertTrue(isinstance(read_resp.json, list) and read_resp.json)

        first = read_resp.json[0]
        self.assertEqual(first.get("content"), outgoing)
        self.assertTrue(str(first.get("content_transport", "")).startswith("linkup-transport-v1|"))
        self.assertEqual(transport_decode_text(first["content_transport"]), outgoing)

        bob_read_resp = self.bob_client.get("/api/messages/alice")
        self.assertEqual(bob_read_resp.status_code, 200)
        self.assertTrue(isinstance(bob_read_resp.json, list) and bob_read_resp.json)

        bob_first = bob_read_resp.json[0]
        self.assertEqual(bob_first.get("content"), outgoing)
        self.assertTrue(str(bob_first.get("content_transport", "")).startswith("linkup-transport-v1|"))
        self.assertEqual(transport_decode_text(bob_first["content_transport"]), outgoing)

    def test_message_api_accepts_plain_content_from_browser(self):
        outgoing = "aaaaa"

        send_resp = self.client.post(
            "/api/messages/bob",
            json={"content": outgoing},
        )
        self.assertEqual(send_resp.status_code, 200)
        self.assertEqual(send_resp.json.get("ok"), True)

        read_resp = self.client.get("/api/messages/bob")
        self.assertEqual(read_resp.status_code, 200)
        self.assertTrue(isinstance(read_resp.json, list) and read_resp.json)
        self.assertEqual(read_resp.json[0].get("content"), outgoing)

        bob_read_resp = self.bob_client.get("/api/messages/alice")
        self.assertEqual(bob_read_resp.status_code, 200)
        self.assertTrue(isinstance(bob_read_resp.json, list) and bob_read_resp.json)
        self.assertEqual(bob_read_resp.json[0].get("content"), outgoing)


if __name__ == "__main__":
    unittest.main()