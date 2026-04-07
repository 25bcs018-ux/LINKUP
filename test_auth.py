import os
import tempfile
import unittest


# Ensure we don't accidentally trigger production guardrails in tests.
os.environ.setdefault("LINKUP_ENV", "development")

# Force verification flow on for these tests.
os.environ["EMAIL_VERIFY_REQUIRED"] = "1"

# Use an isolated sqlite DB file for tests.
_tmp_db = tempfile.NamedTemporaryFile(prefix="linkup_test_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

# Ensure tables are created for the test DB.
os.environ["LINKUP_CREATE_TABLES"] = "1"

from datetime import UTC, datetime, timedelta

from werkzeug.security import generate_password_hash

from app import app, db, User, EmailVerifyOTP


def _utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


class AuthFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with app.app_context():
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        # Dispose engine to avoid sqlite ResourceWarning on some Python versions.
        try:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        except Exception:
            pass

    def setUp(self):
        self.client = app.test_client()

        # Clean tables between tests.
        with app.app_context():
            EmailVerifyOTP.query.delete()
            User.query.delete()
            db.session.commit()

    def _register(self, username="testuser", email="test@example.com", password="password123"):
        return self.client.post(
            "/register",
            data={
                "username": username,
                "email": email,
                "password": password,
                "confirm_password": password,
                "accept_terms": "on",
            },
            follow_redirects=False,
        )

    def test_register_redirects_to_not_verified_when_required(self):
        resp = self._register()
        self.assertEqual(resp.status_code, 302)
        loc = resp.headers.get("Location")
        self.assertTrue(loc and loc.startswith("/email/not-verified"))

        with app.app_context():
            u = User.query.filter_by(username="testuser").first()
            self.assertIsNotNone(u)
            self.assertFalse(bool(u.email_verified))

    def test_login_blocks_unverified_user(self):
        self._register()

        resp = self.client.post(
            "/login",
            data={"username": "testuser", "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers.get("Location", "").startswith("/email/not-verified"))

    def test_login_by_email_blocks_unverified_user(self):
        self._register(username="user2", email="user2@example.com")

        resp = self.client.post(
            "/login",
            data={"username": "user2@example.com", "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.headers.get("Location", "").startswith("/email/not-verified"))

    def test_verify_otp_marks_email_verified_and_logs_in(self):
        self._register(username="user3", email="user3@example.com")

        with app.app_context():
            u = User.query.filter_by(username="user3").first()
            self.assertIsNotNone(u)

            otp = EmailVerifyOTP(
                user_id=int(u.id),
                email=u.email,
                code_hash=generate_password_hash("123456"),
                expires_at=_utcnow() + timedelta(minutes=10),
            )
            db.session.add(otp)
            db.session.commit()

        resp = self.client.post(
            "/api/email/verify/otp/confirm",
            json={"username": "user3", "code": "123456"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json.get("ok"), True)

        with app.app_context():
            u = User.query.filter_by(username="user3").first()
            self.assertTrue(bool(u.email_verified))

        # Session should have user_id set
        with self.client.session_transaction() as sess:
            self.assertIsNotNone(sess.get("user_id"))

        # Verified + logged in user should be able to access chats.
        chats = self.client.get("/chats")
        self.assertEqual(chats.status_code, 200)
        # Newly created account should trigger onboarding tour on first chats load.
        self.assertIn('data-show-onboarding="1"', (chats.get_data(as_text=True) or ''))

    def test_case_insensitive_username_login(self):
        self._register(username="CaseUser", email="case@example.com")

        # Mark verified directly.
        with app.app_context():
            u = User.query.filter_by(username="CaseUser").first()
            self.assertIsNotNone(u)
            u.email_verified = True
            db.session.commit()

        resp = self.client.post(
            "/login",
            data={"username": "caseuser", "password": "password123"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers.get("Location"), "/chats")

    def test_verify_accepts_any_active_otp_not_just_latest(self):
        self._register(username="user4", email="user4@example.com")

        with app.app_context():
            u = User.query.filter_by(username="user4").first()
            self.assertIsNotNone(u)

            # Create two OTPs; the older one has the code we will use.
            old = EmailVerifyOTP(
                user_id=int(u.id),
                email=u.email,
                code_hash=generate_password_hash("111111"),
                expires_at=_utcnow() + timedelta(minutes=10),
                created_at=_utcnow() - timedelta(seconds=5),
            )
            new = EmailVerifyOTP(
                user_id=int(u.id),
                email=u.email,
                code_hash=generate_password_hash("222222"),
                expires_at=_utcnow() + timedelta(minutes=10),
                created_at=_utcnow(),
            )
            db.session.add(old)
            db.session.add(new)
            db.session.commit()

        resp = self.client.post(
            "/api/email/verify/otp/confirm",
            json={"username": "user4", "code": "111111"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json.get("ok"), True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
