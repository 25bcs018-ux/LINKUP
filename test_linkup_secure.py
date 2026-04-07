import os
import tempfile
import unittest
import base64
from unittest.mock import patch


os.environ.setdefault("LINKUP_ENV", "development")

_tmp_db = tempfile.NamedTemporaryFile(prefix="linkup_test_secure_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ["LINKUP_CREATE_TABLES"] = "1"

from app import app, db
from linkup_secure import _SECURE_CHATS, _SECURE_REJECTED, _SECURE_TERMINATED, _SECURE_TOKEN_INDEX


class LinkUpSecureRouteTests(unittest.TestCase):
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
        _SECURE_CHATS.clear()
        _SECURE_TOKEN_INDEX.clear()
        _SECURE_REJECTED.clear()
        _SECURE_TERMINATED.clear()

    def test_linkup_secure_landing_page_is_available(self):
        resp = self.client.get('/linkup-secure/')

        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn('LinkUp Secure', body)
        self.assertIn('>Link<', body)
        self.assertNotIn('Proceed to Sign In', body)
        self.assertNotIn('Request or Create Access', body)

    def test_linkup_secure_link_page_is_available(self):
        resp = self.client.get('/linkup-secure/link')

        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn('Link workspace', body)
        self.assertIn('Create Secure Chat', body)
        self.assertIn('Join Secure Chat', body)

    def test_qw_page_is_available(self):
        resp = self.client.get('/linkup-secure/qw?token=test-token')

        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn('Temporary secure chat', body)
        self.assertIn('Terminate', body)

    def test_secure_manifest_is_available(self):
        resp = self.client.get('/linkup-secure/manifest.webmanifest')

        self.assertEqual(resp.status_code, 200)
        self.assertIn('application/manifest+json', resp.content_type)
        payload = resp.get_json()
        self.assertEqual(payload['name'], 'LinkUp Secure')
        self.assertEqual(payload['scope'], '/linkup-secure/')

    def test_unprotected_chat_requires_accept_then_terminates(self):
        create = self.client.post(
            '/linkup-secure/api/chat/create',
            json={'user_id': 'alice', 'chat_name': 'alpha-chat', 'protected': False},
        )
        self.assertEqual(create.status_code, 200)
        owner_token = create.get_json()['token']

        join = self.client.post(
            '/linkup-secure/api/chat/join',
            json={'user_id': 'bob', 'chat_name': 'alpha-chat'},
        )
        self.assertEqual(join.status_code, 200)
        join_data = join.get_json()
        self.assertEqual(join_data['status'], 'pending')
        guest_token = join_data['token']

        owner_state = self.client.get(f'/linkup-secure/api/chat/session/{owner_token}')
        owner_payload = owner_state.get_json()
        self.assertEqual(owner_payload['status'], 'waiting')
        self.assertEqual(owner_payload['join_request']['user_id'], 'bob')

        decision = self.client.post(
            f'/linkup-secure/api/chat/session/{owner_token}/decision',
            json={'decision': 'accept'},
        )
        self.assertEqual(decision.status_code, 200)

        guest_state = self.client.get(f'/linkup-secure/api/chat/session/{guest_token}')
        guest_payload = guest_state.get_json()
        self.assertEqual(guest_payload['status'], 'connected')
        self.assertEqual(guest_payload['peer_id'], 'alice')

        send = self.client.post(
            f'/linkup-secure/api/chat/session/{owner_token}/message',
            json={'content': 'temporary hello'},
        )
        self.assertEqual(send.status_code, 200)

        guest_messages = self.client.get(f'/linkup-secure/api/chat/session/{guest_token}?after_id=0')
        guest_messages_payload = guest_messages.get_json()
        self.assertEqual(guest_messages_payload['messages'][0]['content'], 'temporary hello')

        terminate = self.client.post(f'/linkup-secure/api/chat/session/{owner_token}/terminate')
        self.assertEqual(terminate.status_code, 200)

        owner_terminated = self.client.get(f'/linkup-secure/api/chat/session/{owner_token}')
        owner_payload = owner_terminated.get_json()
        self.assertEqual(owner_payload['status'], 'terminated')
        self.assertNotIn('chat_name', owner_payload)
        self.assertNotIn('user_id', owner_payload)
        self.assertNotIn('peer_id', owner_payload)
        guest_terminated = self.client.get(f'/linkup-secure/api/chat/session/{guest_token}')
        guest_payload = guest_terminated.get_json()
        self.assertEqual(guest_payload['status'], 'terminated')
        self.assertNotIn('chat_name', guest_payload)
        self.assertNotIn('user_id', guest_payload)
        self.assertNotIn('peer_id', guest_payload)
        self.assertEqual(_SECURE_CHATS, {})
        self.assertEqual(_SECURE_TOKEN_INDEX, {})
        self.assertEqual(_SECURE_TERMINATED, set())

    def test_protected_chat_requires_password_and_auto_connects(self):
        create = self.client.post(
            '/linkup-secure/api/chat/create',
            json={'user_id': 'owner', 'chat_name': 'vault-chat', 'protected': True, 'password': 'secret123'},
        )
        self.assertEqual(create.status_code, 200)
        owner_token = create.get_json()['token']

        missing = self.client.post(
            '/linkup-secure/api/chat/join',
            json={'user_id': 'guest', 'chat_name': 'vault-chat'},
        )
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.get_json()['error'], 'password_required')

        wrong = self.client.post(
            '/linkup-secure/api/chat/join',
            json={'user_id': 'guest', 'chat_name': 'vault-chat', 'password': 'wrong'},
        )
        self.assertEqual(wrong.status_code, 403)
        self.assertEqual(wrong.get_json()['error'], 'invalid_password')

        joined = self.client.post(
            '/linkup-secure/api/chat/join',
            json={'user_id': 'guest', 'chat_name': 'vault-chat', 'password': 'secret123'},
        )
        self.assertEqual(joined.status_code, 200)
        guest_token = joined.get_json()['token']

        owner_state = self.client.get(f'/linkup-secure/api/chat/session/{owner_token}')
        self.assertEqual(owner_state.get_json()['status'], 'connected')
        guest_state = self.client.get(f'/linkup-secure/api/chat/session/{guest_token}')
        self.assertEqual(guest_state.get_json()['status'], 'connected')

    def test_temporary_chat_attachment_is_delivered_and_not_persisted(self):
        create = self.client.post(
            '/linkup-secure/api/chat/create',
            json={'user_id': 'alice', 'chat_name': 'attach-chat', 'protected': True, 'password': 'attach123'},
        )
        self.assertEqual(create.status_code, 200)
        owner_token = create.get_json()['token']

        joined = self.client.post(
            '/linkup-secure/api/chat/join',
            json={'user_id': 'bob', 'chat_name': 'attach-chat', 'password': 'attach123'},
        )
        self.assertEqual(joined.status_code, 200)
        guest_token = joined.get_json()['token']

        attachment_payload = {
            'name': 'hello.txt',
            'mime': 'text/plain',
            'data': base64.b64encode(b'hello from temp chat').decode('ascii'),
            'size': len(b'hello from temp chat'),
        }
        send = self.client.post(
            f'/linkup-secure/api/chat/session/{owner_token}/message',
            json={'content': 'see attachment', 'attachment': attachment_payload},
        )
        self.assertEqual(send.status_code, 200)

        guest_state = self.client.get(f'/linkup-secure/api/chat/session/{guest_token}?after_id=0')
        payload = guest_state.get_json()
        self.assertEqual(payload['status'], 'connected')
        self.assertEqual(payload['messages'][0]['content'], 'see attachment')
        self.assertEqual(payload['messages'][0]['attachment']['name'], 'hello.txt')
        self.assertEqual(payload['messages'][0]['attachment']['mime'], 'text/plain')

        terminate = self.client.post(f'/linkup-secure/api/chat/session/{owner_token}/terminate')
        self.assertEqual(terminate.status_code, 200)
        self.assertEqual(_SECURE_CHATS, {})
        self.assertEqual(_SECURE_TOKEN_INDEX, {})

    def test_secure_api_returns_json_when_payload_is_too_large(self):
        original_limit = app.config['MAX_CONTENT_LENGTH']
        app.config['MAX_CONTENT_LENGTH'] = 64
        try:
            resp = self.client.post(
                '/linkup-secure/api/chat/create',
                json={'user_id': 'alice', 'chat_name': 'x' * 128, 'protected': False},
            )
        finally:
            app.config['MAX_CONTENT_LENGTH'] = original_limit

        self.assertEqual(resp.status_code, 413)
        self.assertTrue(resp.is_json)
        self.assertEqual(resp.get_json()['error'], 'payload_too_large')

    def test_inactivity_countdown_requires_both_members_to_remain(self):
        with patch('linkup_secure._now_ts', return_value=1000.0):
            create = self.client.post(
                '/linkup-secure/api/chat/create',
                json={'user_id': 'alice', 'chat_name': 'idle-chat', 'protected': True, 'password': 'keepalive'},
            )
            owner_token = create.get_json()['token']

            joined = self.client.post(
                '/linkup-secure/api/chat/join',
                json={'user_id': 'bob', 'chat_name': 'idle-chat', 'password': 'keepalive'},
            )
            guest_token = joined.get_json()['token']

        with patch('linkup_secure._now_ts', return_value=1300.0):
            owner_state = self.client.get(f'/linkup-secure/api/chat/session/{owner_token}')
            owner_payload = owner_state.get_json()
            self.assertEqual(owner_payload['status'], 'connected')
            self.assertTrue(owner_payload['idle_prompt']['active'])
            self.assertEqual(owner_payload['idle_prompt']['seconds_left'], 15)
            self.assertFalse(owner_payload['idle_prompt']['own_remain'])
            self.assertFalse(owner_payload['idle_prompt']['peer_remain'])

        with patch('linkup_secure._now_ts', return_value=1305.0):
            remain_owner = self.client.post(f'/linkup-secure/api/chat/session/{owner_token}/remain')
            owner_remain_payload = remain_owner.get_json()
            self.assertEqual(remain_owner.status_code, 200)
            self.assertFalse(owner_remain_payload['continued'])
            self.assertEqual(owner_remain_payload['status'], 'countdown')

        with patch('linkup_secure._now_ts', return_value=1306.0):
            guest_state = self.client.get(f'/linkup-secure/api/chat/session/{guest_token}')
            guest_payload = guest_state.get_json()
            self.assertTrue(guest_payload['idle_prompt']['peer_remain'])
            self.assertFalse(guest_payload['idle_prompt']['own_remain'])

            remain_guest = self.client.post(f'/linkup-secure/api/chat/session/{guest_token}/remain')
            guest_remain_payload = remain_guest.get_json()
            self.assertEqual(remain_guest.status_code, 200)
            self.assertTrue(guest_remain_payload['continued'])
            self.assertEqual(guest_remain_payload['status'], 'connected')

            resumed_owner_state = self.client.get(f'/linkup-secure/api/chat/session/{owner_token}')
            resumed_owner_payload = resumed_owner_state.get_json()
            self.assertEqual(resumed_owner_payload['status'], 'connected')
            self.assertNotIn('idle_prompt', resumed_owner_payload)

    def test_inactivity_countdown_terminates_chat_without_both_confirmations(self):
        with patch('linkup_secure._now_ts', return_value=2000.0):
            create = self.client.post(
                '/linkup-secure/api/chat/create',
                json={'user_id': 'alice', 'chat_name': 'idle-timeout', 'protected': True, 'password': 'keepalive'},
            )
            owner_token = create.get_json()['token']

            joined = self.client.post(
                '/linkup-secure/api/chat/join',
                json={'user_id': 'bob', 'chat_name': 'idle-timeout', 'password': 'keepalive'},
            )
            guest_token = joined.get_json()['token']

        with patch('linkup_secure._now_ts', return_value=2300.0):
            owner_state = self.client.get(f'/linkup-secure/api/chat/session/{owner_token}')
            self.assertEqual(owner_state.get_json()['status'], 'connected')
            self.assertIn('idle_prompt', owner_state.get_json())

        with patch('linkup_secure._now_ts', return_value=2316.0):
            guest_state = self.client.get(f'/linkup-secure/api/chat/session/{guest_token}')
            guest_payload = guest_state.get_json()
            self.assertEqual(guest_payload['status'], 'terminated')

            owner_state = self.client.get(f'/linkup-secure/api/chat/session/{owner_token}')
            owner_payload = owner_state.get_json()
            self.assertEqual(owner_payload['status'], 'terminated')

        self.assertEqual(_SECURE_CHATS, {})
        self.assertEqual(_SECURE_TOKEN_INDEX, {})
        self.assertEqual(_SECURE_TERMINATED, set())


if __name__ == '__main__':
    unittest.main(verbosity=2)