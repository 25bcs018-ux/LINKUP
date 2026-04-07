import os
import tempfile
import unittest


# Ensure we don't accidentally trigger production guardrails in tests.
os.environ.setdefault("LINKUP_ENV", "development")

# Use an isolated sqlite DB file for tests.
_tmp_db = tempfile.NamedTemporaryFile(prefix="linkup_test_polls_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

# Ensure tables are created for the test DB.
os.environ["LINKUP_CREATE_TABLES"] = "1"

from werkzeug.security import generate_password_hash

from app import app, db, User, Group, GroupMember, GroupInvite, GroupPoll, GroupPollVote


class GroupPollsTests(unittest.TestCase):
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
            GroupPollVote.query.delete()
            GroupPoll.query.delete()
            GroupInvite.query.delete()
            GroupMember.query.delete()
            Group.query.delete()
            User.query.delete()
            db.session.commit()

    def _mk_user(self, username: str) -> int:
        with app.app_context():
            u = User(
                username=username,
                email=f"{username}@example.com",
                password=generate_password_hash("pw"),
                email_verified=True,
            )
            db.session.add(u)
            db.session.commit()
            return int(u.id)

    def _login(self, user_id: int, username: str) -> None:
        with self.client.session_transaction() as sess:
            sess["user_id"] = int(user_id)
            sess["username"] = username

    def test_invite_poll_vote_approves_and_creates_invite(self):
        alice_id = self._mk_user("alice")
        bob_id = self._mk_user("bob")
        charlie_id = self._mk_user("charlie")

        with app.app_context():
            g = Group(name="G", owner_id=alice_id)
            db.session.add(g)
            db.session.commit()
            gid = int(g.id)
            db.session.add(GroupMember(group_id=gid, user_id=alice_id))
            db.session.add(GroupMember(group_id=gid, user_id=bob_id))
            db.session.commit()

        # Alice starts invite poll for charlie.
        self._login(alice_id, "alice")
        r = self.client.post(f"/api/groups/{gid}/invite", json={"username": "charlie"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json.get("ok"), True)
        self.assertIn(r.json.get("status"), ("poll_created", "poll_open"))

        polls = self.client.get(f"/api/groups/{gid}/polls")
        self.assertEqual(polls.status_code, 200)
        self.assertIsInstance(polls.json, list)
        open_invite = next((p for p in polls.json if p.get("kind") == "invite" and p.get("status") == "open" and p.get("target_username") == "charlie"), None)
        self.assertIsNotNone(open_invite)
        poll_id = int(open_invite["id"])

        # Bob votes yes to reach majority of 2/2.
        self._login(bob_id, "bob")
        v = self.client.post(f"/api/groups/polls/{poll_id}/vote", json={"vote": "yes"})
        self.assertEqual(v.status_code, 200)
        self.assertEqual(v.json.get("ok"), True)
        self.assertEqual(v.json.get("result", {}).get("decided"), True)
        self.assertEqual(v.json.get("result", {}).get("status"), "approved")

        with app.app_context():
            inv = GroupInvite.query.filter_by(group_id=gid, invitee_id=charlie_id, status="pending").first()
            self.assertIsNotNone(inv)

    def test_remove_poll_subject_cannot_vote_and_approval_removes_member(self):
        alice_id = self._mk_user("alice")
        bob_id = self._mk_user("bob")
        charlie_id = self._mk_user("charlie")

        with app.app_context():
            g = Group(name="G", owner_id=alice_id)
            db.session.add(g)
            db.session.commit()
            gid = int(g.id)
            db.session.add(GroupMember(group_id=gid, user_id=alice_id))
            db.session.add(GroupMember(group_id=gid, user_id=bob_id))
            db.session.add(GroupMember(group_id=gid, user_id=charlie_id))
            db.session.commit()

        # Alice starts removal poll for bob.
        self._login(alice_id, "alice")
        r = self.client.post(f"/api/groups/{gid}/members/remove", json={"username": "bob"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json.get("ok"), True)
        self.assertIn(r.json.get("status"), ("poll_created", "poll_open"))

        polls = self.client.get(f"/api/groups/{gid}/polls")
        open_remove = next((p for p in polls.json if p.get("kind") == "remove" and p.get("status") == "open" and p.get("target_username") == "bob"), None)
        self.assertIsNotNone(open_remove)
        poll_id = int(open_remove["id"])

        # Bob (subject) cannot vote.
        self._login(bob_id, "bob")
        denied = self.client.post(f"/api/groups/polls/{poll_id}/vote", json={"vote": "no"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.json.get("error"), "poll_subject_cannot_vote")

        # Charlie votes yes. Eligible voters are alice+charlie, so majority=2.
        self._login(charlie_id, "charlie")
        v = self.client.post(f"/api/groups/polls/{poll_id}/vote", json={"vote": "yes"})
        self.assertEqual(v.status_code, 200)
        self.assertEqual(v.json.get("ok"), True)
        self.assertEqual(v.json.get("result", {}).get("decided"), True)
        self.assertEqual(v.json.get("result", {}).get("status"), "approved")

        with app.app_context():
            self.assertIsNone(GroupMember.query.filter_by(group_id=gid, user_id=bob_id).first())


if __name__ == "__main__":
    unittest.main(verbosity=2)
