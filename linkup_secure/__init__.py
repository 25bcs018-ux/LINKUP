import base64
import binascii
import json
import secrets
import threading
import time

from flask import Blueprint, Response, jsonify, render_template, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from crypto import CryptoError, decrypt_text, encrypt_text


blueprint = Blueprint(
    'linkup_secure',
    __name__,
    url_prefix='/linkup-secure',
    template_folder='templates',
    static_folder='static',
)


_SECURE_CHAT_LOCK = threading.RLock()
_SECURE_CHATS: dict[str, dict] = {}
_SECURE_TOKEN_INDEX: dict[str, tuple[str, str]] = {}
_SECURE_REJECTED: dict[str, dict] = {}
_SECURE_TERMINATED: set[str] = set()
_MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
_IDLE_INACTIVITY_SECONDS = 5 * 60
_IDLE_COUNTDOWN_SECONDS = 15


def _chat_key(chat_name: str) -> str:
    return (chat_name or '').strip().lower()


def _new_token() -> str:
    return secrets.token_urlsafe(18)


def _now_ts() -> float:
    return time.time()


def _find_chat_by_token(token: str):
    token = (token or '').strip()
    if not token:
        return None, None, None
    with _SECURE_CHAT_LOCK:
        hit = _SECURE_TOKEN_INDEX.get(token)
        if not hit:
            return None, None, None
        chat_key, role = hit
        chat = _SECURE_CHATS.get(chat_key)
        if not chat:
            return None, None, None
        return chat_key, chat, role


def _clear_chat(chat_key: str) -> None:
    chat = _SECURE_CHATS.pop(chat_key, None)
    if not chat:
        return

    owner = chat.get('owner', {})
    guest = chat.get('guest') or {}
    pending = chat.get('pending_request') or {}
    for token in (owner.get('token'), guest.get('token'), pending.get('token')):
        if token:
            _SECURE_TOKEN_INDEX.pop(token, None)

    owner.clear()
    guest.clear()
    pending.clear()
    messages = chat.get('messages')
    if isinstance(messages, list):
        messages.clear()
    chat.clear()


def _mark_chat_active(chat: dict) -> None:
    chat['last_activity_at'] = _now_ts()
    chat['idle_prompt'] = None


def _prompt_remain_roles(prompt: dict) -> set[str]:
    remain_roles = prompt.get('remain_roles')
    if isinstance(remain_roles, set):
        return remain_roles

    remain_roles = set(remain_roles or ())
    prompt['remain_roles'] = remain_roles
    return remain_roles


def _terminate_chat(chat_key: str, chat: dict) -> None:
    owner = chat.get('owner') or {}
    guest = chat.get('guest') or {}
    pending = chat.get('pending_request') or {}
    for item in (owner, guest, pending):
        token_value = item.get('token')
        if token_value:
            _SECURE_TERMINATED.add(token_value)
    _clear_chat(chat_key)


def _sync_idle_prompt(chat_key: str, chat: dict) -> bool:
    if not chat.get('guest'):
        chat['idle_prompt'] = None
        return False

    now = _now_ts()
    prompt = chat.get('idle_prompt')
    if isinstance(prompt, dict):
        remain_roles = _prompt_remain_roles(prompt)
        if {'owner', 'guest'}.issubset(remain_roles):
            _mark_chat_active(chat)
            return False
        if now >= float(prompt.get('deadline_at') or 0):
            _terminate_chat(chat_key, chat)
            return True
        return False

    last_activity_at = float(chat.get('last_activity_at') or now)
    if now - last_activity_at >= _IDLE_INACTIVITY_SECONDS:
        chat['idle_prompt'] = {
            'deadline_at': now + _IDLE_COUNTDOWN_SECONDS,
            'remain_roles': set(),
        }
    return False


def _idle_prompt_payload(chat: dict, role: str):
    prompt = chat.get('idle_prompt')
    if not isinstance(prompt, dict) or role not in ('owner', 'guest'):
        return None

    deadline_at = float(prompt.get('deadline_at') or 0)
    seconds_left = max(int((deadline_at - _now_ts()) + 0.999), 0)
    remain_roles = _prompt_remain_roles(prompt)

    other_role = 'guest' if role == 'owner' else 'owner'
    return {
        'active': True,
        'deadline_at': deadline_at,
        'seconds_left': seconds_left,
        'own_remain': role in remain_roles,
        'peer_remain': other_role in remain_roles,
    }


def _safe_decrypt(value: str) -> str:
    try:
        return decrypt_text(value)
    except CryptoError:
        return '[message unavailable]'
    except Exception:
        return '[message unavailable]'


def _safe_decrypt_attachment(value: str):
    try:
        raw = decrypt_text(value)
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return {
        'name': str(data.get('name') or ''),
        'mime': str(data.get('mime') or 'application/octet-stream'),
        'data': str(data.get('data') or ''),
        'size': int(data.get('size') or 0),
        'kind': str(data.get('kind') or 'file'),
    }


def _normalize_attachment(payload):
    if not isinstance(payload, dict):
        return None

    name = str(payload.get('name') or '').strip()
    mime = str(payload.get('mime') or 'application/octet-stream').strip() or 'application/octet-stream'
    data = str(payload.get('data') or '').strip()
    if not name or not data:
        raise ValueError('invalid_attachment')

    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError('invalid_attachment') from exc

    if len(raw) == 0:
        raise ValueError('invalid_attachment')
    if len(raw) > _MAX_ATTACHMENT_BYTES:
        raise ValueError('attachment_too_large')

    normalized_b64 = base64.b64encode(raw).decode('ascii')
    return {
        'name': name[:140],
        'mime': mime[:120],
        'data': normalized_b64,
        'size': len(raw),
        'kind': 'image' if mime.startswith('image/') else 'file',
    }


@blueprint.get('/')
def home():
    return render_template('linkup_secure/index.html')


@blueprint.get('/link')
def link():
    return render_template('linkup_secure/link.html')


@blueprint.get('/manifest.webmanifest')
def secure_manifest():
    payload = {
        'name': 'LinkUp Secure',
        'short_name': 'Secure',
        'description': 'LinkUp Secure temporary private chat workspace.',
        'start_url': url_for('linkup_secure.home'),
        'scope': '/linkup-secure/',
        'display': 'standalone',
        'display_override': ['standalone', 'window-controls-overlay'],
        'orientation': 'portrait',
        'background_color': '#06131a',
        'theme_color': '#06131a',
        'icons': [
            {
                'src': url_for('static', filename='linkup_logo.svg'),
                'sizes': 'any',
                'type': 'image/svg+xml',
                'purpose': 'any'
            }
        ],
    }
    return Response(json.dumps(payload), mimetype='application/manifest+json')


@blueprint.get('/qw')
def qw():
    token = (request.args.get('token') or '').strip()
    return render_template('linkup_secure/qw.html', token=token)


@blueprint.post('/api/chat/create')
def api_create_chat():
    payload = request.get_json(silent=True) or {}
    user_id = (payload.get('user_id') or '').strip()
    chat_name = (payload.get('chat_name') or '').strip()
    protected = bool(payload.get('protected'))
    password = payload.get('password') or ''

    if not user_id or not chat_name:
        return jsonify({'error': 'missing_fields'}), 400
    if len(user_id) > 80 or len(chat_name) > 120:
        return jsonify({'error': 'field_too_long'}), 400
    if protected and not str(password).strip():
        return jsonify({'error': 'password_required'}), 400

    chat_key = _chat_key(chat_name)
    with _SECURE_CHAT_LOCK:
        if chat_key in _SECURE_CHATS:
            return jsonify({'error': 'chat_exists'}), 409

        owner_token = _new_token()
        _SECURE_CHATS[chat_key] = {
            'chat_name': chat_name,
            'protected': protected,
            'password_hash': generate_password_hash(password) if protected else None,
            'owner': {'user_id': user_id, 'token': owner_token},
            'guest': None,
            'pending_request': None,
            'messages': [],
            'next_message_id': 1,
            'last_activity_at': _now_ts(),
            'idle_prompt': None,
        }
        _SECURE_TOKEN_INDEX[owner_token] = (chat_key, 'owner')

    return jsonify({
        'ok': True,
        'status': 'waiting',
        'token': owner_token,
        'next_url': url_for('linkup_secure.qw', token=owner_token),
    })


@blueprint.post('/api/chat/join')
def api_join_chat():
    payload = request.get_json(silent=True) or {}
    user_id = (payload.get('user_id') or '').strip()
    chat_name = (payload.get('chat_name') or '').strip()
    password = payload.get('password') or ''

    if not user_id or not chat_name:
        return jsonify({'error': 'missing_fields'}), 400

    chat_key = _chat_key(chat_name)
    with _SECURE_CHAT_LOCK:
        chat = _SECURE_CHATS.get(chat_key)
        if not chat:
            return jsonify({'error': 'chat_not_found'}), 404
        if chat.get('guest'):
            return jsonify({'error': 'chat_in_use'}), 409
        if chat.get('protected'):
            if not str(password).strip():
                return jsonify({'error': 'password_required'}), 400
            if not check_password_hash(chat.get('password_hash') or '', str(password)):
                return jsonify({'error': 'invalid_password'}), 403
            guest_token = _new_token()
            chat['guest'] = {'user_id': user_id, 'token': guest_token}
            _SECURE_TOKEN_INDEX[guest_token] = (chat_key, 'guest')
            _mark_chat_active(chat)
            return jsonify({
                'ok': True,
                'status': 'connected',
                'token': guest_token,
                'next_url': url_for('linkup_secure.qw', token=guest_token),
            })

        if chat.get('pending_request'):
            return jsonify({'error': 'join_request_pending'}), 409

        pending_token = _new_token()
        chat['pending_request'] = {
            'user_id': user_id,
            'token': pending_token,
            'status': 'pending',
        }
        _SECURE_TOKEN_INDEX[pending_token] = (chat_key, 'pending')

    return jsonify({
        'ok': True,
        'status': 'pending',
        'token': pending_token,
        'next_url': url_for('linkup_secure.qw', token=pending_token),
    })


@blueprint.get('/api/chat/session/<string:token>')
def api_chat_session(token: str):
    token = (token or '').strip()
    after_id_raw = request.args.get('after_id', '0')
    try:
        after_id = max(int(after_id_raw), 0)
    except Exception:
        after_id = 0

    with _SECURE_CHAT_LOCK:
        rejected = _SECURE_REJECTED.pop(token, None)
        if rejected:
            return jsonify({'ok': True, 'status': 'rejected', **rejected})

        if token in _SECURE_TERMINATED:
            _SECURE_TERMINATED.discard(token)
            return jsonify({'ok': True, 'status': 'terminated'})

        chat_key, chat, role = _find_chat_by_token(token)
        if not chat:
            return jsonify({'error': 'session_not_found'}), 404
        if _sync_idle_prompt(chat_key, chat):
            if token in _SECURE_TERMINATED:
                _SECURE_TERMINATED.discard(token)
                return jsonify({'ok': True, 'status': 'terminated'})
            return jsonify({'error': 'session_not_found'}), 404

        owner = chat['owner']
        guest = chat.get('guest')
        pending = chat.get('pending_request')

        if role == 'owner':
            status = 'connected' if guest else 'waiting'
            user_id = owner['user_id']
            peer_id = guest['user_id'] if guest else None
        elif role == 'guest':
            status = 'connected'
            user_id = guest['user_id'] if guest else ''
            peer_id = owner['user_id']
        else:
            status = (pending or {}).get('status', 'pending')
            user_id = (pending or {}).get('user_id', '')
            peer_id = owner['user_id']

        items = []
        for item in chat.get('messages', []):
            if int(item['id']) <= after_id:
                continue
            items.append({
                'id': int(item['id']),
                'sender_id': item['sender_id'],
                'content': _safe_decrypt(item['content']),
                'attachment': _safe_decrypt_attachment(item['attachment']) if item.get('attachment') else None,
                'own': item['sender_id'] == user_id,
            })

        response = {
            'ok': True,
            'status': status,
            'role': role,
            'chat_name': chat['chat_name'],
            'user_id': user_id,
            'peer_id': peer_id,
            'protected': bool(chat.get('protected')),
            'messages': items,
        }
        if role == 'owner' and pending:
            response['join_request'] = {
                'user_id': pending['user_id'],
                'status': pending['status'],
            }
        idle_prompt = _idle_prompt_payload(chat, role)
        if idle_prompt:
            response['idle_prompt'] = idle_prompt
        return jsonify(response)


@blueprint.post('/api/chat/session/<string:token>/decision')
def api_chat_decision(token: str):
    payload = request.get_json(silent=True) or {}
    decision = (payload.get('decision') or '').strip().lower()
    if decision not in ('accept', 'reject'):
        return jsonify({'error': 'invalid_decision'}), 400

    with _SECURE_CHAT_LOCK:
        chat_key, chat, role = _find_chat_by_token(token)
        if not chat or role != 'owner':
            return jsonify({'error': 'session_not_found'}), 404
        pending = chat.get('pending_request')
        if not pending:
            return jsonify({'error': 'no_pending_request'}), 404

        pending_token = pending['token']
        if decision == 'accept':
            chat['guest'] = {'user_id': pending['user_id'], 'token': pending_token}
            chat['pending_request'] = None
            _SECURE_TOKEN_INDEX[pending_token] = (chat_key, 'guest')
            _mark_chat_active(chat)
            return jsonify({'ok': True, 'status': 'connected'})

        chat['pending_request'] = None
        _SECURE_TOKEN_INDEX.pop(pending_token, None)
        _SECURE_REJECTED[pending_token] = {
            'chat_name': chat['chat_name'],
            'user_id': pending['user_id'],
        }
        return jsonify({'ok': True, 'status': 'rejected'})


@blueprint.post('/api/chat/session/<string:token>/message')
def api_chat_message(token: str):
    payload = request.get_json(silent=True) or {}
    content = (payload.get('content') or '').strip()
    try:
        attachment = _normalize_attachment(payload.get('attachment')) if payload.get('attachment') is not None else None
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if not content and not attachment:
        return jsonify({'error': 'empty_message'}), 400
    if len(content) > 2000:
        return jsonify({'error': 'message_too_long'}), 400

    with _SECURE_CHAT_LOCK:
        chat_key, chat, role = _find_chat_by_token(token)
        if not chat or role not in ('owner', 'guest'):
            return jsonify({'error': 'session_not_found'}), 404
        if not chat.get('guest'):
            return jsonify({'error': 'chat_not_connected'}), 409
        if _sync_idle_prompt(chat_key, chat):
            return jsonify({'ok': True, 'status': 'terminated'}), 409
        if chat.get('idle_prompt'):
            return jsonify({'error': 'idle_countdown_active'}), 409

        sender_id = chat['owner']['user_id'] if role == 'owner' else chat['guest']['user_id']
        message_id = int(chat['next_message_id'])
        chat['next_message_id'] = message_id + 1
        _mark_chat_active(chat)
        chat['messages'].append({
            'id': message_id,
            'sender_id': sender_id,
            'content': encrypt_text(content),
            'attachment': encrypt_text(json.dumps(attachment)) if attachment else None,
        })

    return jsonify({'ok': True, 'id': message_id})


@blueprint.post('/api/chat/session/<string:token>/activity')
def api_chat_activity(token: str):
    with _SECURE_CHAT_LOCK:
        chat_key, chat, role = _find_chat_by_token(token)
        if not chat or role not in ('owner', 'guest'):
            return jsonify({'error': 'session_not_found'}), 404
        if not chat.get('guest'):
            return jsonify({'ok': True, 'status': 'waiting'})
        if _sync_idle_prompt(chat_key, chat):
            return jsonify({'ok': True, 'status': 'terminated'})
        if chat.get('idle_prompt'):
            return jsonify({'ok': True, 'status': 'countdown'})

        _mark_chat_active(chat)

    return jsonify({'ok': True, 'status': 'connected'})


@blueprint.post('/api/chat/session/<string:token>/remain')
def api_chat_remain(token: str):
    with _SECURE_CHAT_LOCK:
        chat_key, chat, role = _find_chat_by_token(token)
        if not chat or role not in ('owner', 'guest'):
            return jsonify({'error': 'session_not_found'}), 404
        if not chat.get('guest'):
            return jsonify({'error': 'chat_not_connected'}), 409
        if _sync_idle_prompt(chat_key, chat):
            return jsonify({'ok': True, 'status': 'terminated'}), 409

        prompt = chat.get('idle_prompt')
        if not isinstance(prompt, dict):
            return jsonify({'error': 'countdown_not_active'}), 409

        remain_roles = _prompt_remain_roles(prompt)
        remain_roles.add(role)

        if {'owner', 'guest'}.issubset(remain_roles):
            _mark_chat_active(chat)
            return jsonify({'ok': True, 'status': 'connected', 'continued': True})

        return jsonify({'ok': True, 'status': 'countdown', 'continued': False})


@blueprint.post('/api/chat/session/<string:token>/terminate')
def api_chat_terminate(token: str):
    with _SECURE_CHAT_LOCK:
        chat_key, chat, _role = _find_chat_by_token(token)
        if not chat:
            return jsonify({'error': 'session_not_found'}), 404

        _terminate_chat(chat_key, chat)

    return jsonify({'ok': True, 'status': 'terminated'})