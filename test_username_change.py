import os
import tempfile
import unittest


# Ensure we don't accidentally trigger production guardrails in tests.
os.environ.setdefault("LINKUP_ENV", "development")

# Use an isolated sqlite DB file for tests.
_tmp_db = tempfile.NamedTemporaryFile(prefix="linkup_test_username_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

# Ensure tables are created for the test DB.
os.environ["LINKUP_CREATE_TABLES"] = "1"

from werkzeug.security import generate_password_hash

from app import app, db, User, ContactRequest, Group, GroupMember, GroupPoll


class UsernameChangeTests(unittest.TestCase):
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
        with app.app_context():
            GroupPoll.query.delete()
            GroupMember.query.delete()
            Group.query.delete()
            ContactRequest.query.delete()
            User.query.delete()
            db.session.commit()

    def test_username_change_leaves_groups_and_starts_invite_poll(self):
        with app.app_context():
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

            # Accepted contact relationship (will be wiped).
            db.session.add(ContactRequest(requester_id=alice.id, addressee_id=bob.id, status="accepted"))
            db.session.commit()

            # Group with alice + bob.
            g = Group(name="Test Group", owner_id=bob.id)
            db.session.add(g)
            db.session.commit()
            db.session.add(GroupMember(group_id=g.id, user_id=alice.id))
            db.session.add(GroupMember(group_id=g.id, user_id=bob.id))
            db.session.commit()

            alice_id = int(alice.id)
            group_id = int(g.id)

        # Log in as alice.
        with self.client.session_transaction() as sess:
            sess["user_id"] = alice_id
            sess["username"] = "alice"

        resp = self.client.post(
            "/api/account/username/finalize",
            json={
                "new_username": "alice2",
                "current_password": "pw",
                "selected_contacts": ["bob"],
                "selected_groups": [group_id],
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json.get("ok"), True)
        self.assertEqual(resp.json.get("new_username"), "alice2")

        with app.app_context():
            alice = db.session.get(User, alice_id)
            self.assertIsNotNone(alice)
            self.assertEqual(alice.username, "alice2")

            # Contacts wiped and replaced with a pending request.
            rels = ContactRequest.query.all()
            self.assertEqual(len(rels), 1)
            self.assertEqual(rels[0].requester_id, alice_id)
            self.assertEqual(rels[0].status, "pending")

            # Alice is no longer a member.
            self.assertIsNone(GroupMember.query.filter_by(group_id=group_id, user_id=alice_id).first())

            # Poll exists to invite alice back.
            poll = GroupPoll.query.filter_by(group_id=group_id, kind="invite", status="open", target_user_id=alice_id).first()
            self.assertIsNotNone(poll)
            self.assertEqual(poll.target_username, "alice2")


if __name__ == "__main__":
    unittest.main(verbosity=2)
