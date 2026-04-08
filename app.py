# backend code
from datetime import UTC, datetime, timedelta
import hmac
import logging
import os
import random
import re
import shutil
from pathlib import Path
import smtplib
from email.message import EmailMessage
import secrets
from typing import Optional
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

from flask import Flask, request, render_template, redirect, url_for, session, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import requests
from authlib.jose import JsonWebKey, jwt

from crypto import encrypt_text, decrypt_text, CryptoError
from encryption.pipeline import transport_decode_text, transport_encode_text
import nova_ai
from linkup_secure import blueprint as linkup_secure_blueprint

def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


ENV_NAME = (os.environ.get("LINKUP_ENV") or os.environ.get("FLASK_ENV") or "development").strip().lower()
PRODUCTION = ENV_NAME in ("prod", "production")
EMAIL_VERIFY_LINK_ENABLED = _env_bool("LINKUP_EMAIL_VERIFY_LINK_ENABLED", default=(not PRODUCTION))


def _normalize_db_uri(uri: str) -> str:
    if uri.startswith("postgres://"):
        return "postgresql://" + uri[len("postgres://"):]
    return uri


app = Flask(__name__)

secret_key = os.environ.get("SECRET_KEY", "").strip()
if not secret_key:
    if PRODUCTION:
        raise RuntimeError("SECRET_KEY must be set in production")
    secret_key = "dev-secret-key-change-me"
elif PRODUCTION and secret_key == "dev-secret-key-change-me":
    raise RuntimeError("SECRET_KEY must be set to a strong value in production")

if PRODUCTION and not os.environ.get("CHAT_ENC_KEY", "").strip():
    raise RuntimeError("CHAT_ENC_KEY must be set in production")

db_uri = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("SQLALCHEMY_DATABASE_URI")
    or "sqlite:///LINKUP.db"
)
db_uri = _normalize_db_uri(db_uri)

app.secret_key = secret_key
app.config.update(
    SQLALCHEMY_DATABASE_URI=db_uri,
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,  # allow attachments; enforce per-endpoint limits below
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=PRODUCTION,
    PREFERRED_URL_SCHEME="https" if PRODUCTION else "http",
)

if _env_bool("LINKUP_PROXY_FIX", default=PRODUCTION):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

log_level = os.environ.get("LOG_LEVEL", "INFO" if PRODUCTION else "DEBUG").upper()
logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

db = SQLAlchemy(app)

app.register_blueprint(linkup_secure_blueprint)


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _presence_window_seconds() -> int:
    try:
        return max(20, int(os.environ.get("LINKUP_PRESENCE_WINDOW_SECONDS") or "70"))
    except Exception:
        return 70


def _is_api_request() -> bool:
    try:
        path = request.path or ''
    except Exception:
        return False
    return path.startswith('/api/') or path.startswith('/linkup-secure/api/')


def _db_get(model, primary_key):
    return db.session.get(model, primary_key)


@app.errorhandler(404)
def _api_404(e):
    if _is_api_request():
        return jsonify({'error': 'not_found'}), 404
    return e


@app.errorhandler(405)
def _api_405(e):
    if _is_api_request():
        return jsonify({'error': 'method_not_allowed'}), 405
    return e


@app.errorhandler(413)
def _api_413(e):
    if _is_api_request():
        return jsonify({'error': 'payload_too_large'}), 413
    return e


@app.errorhandler(500)
def _api_500(e):
    if _is_api_request():
        return jsonify({'error': 'server_error'}), 500
    return e


@app.before_request
def _csrf_protect():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return None

    path = request.path or ''
    is_api = path.startswith('/api/') or path.startswith('/linkup-secure/api/')
    protected_form_paths = {
        '/login',
        '/register',
        '/support',
        '/email/resend',
    }

    if not is_api and path not in protected_form_paths:
        return None

    session_token = session.get('_csrf_token')
    if not session_token:
        if is_api:
            return jsonify({'error': 'csrf_missing_or_invalid'}), 403
        return ('Forbidden', 403)

    header_token = request.headers.get('X-CSRF-Token') or request.headers.get('X-CSRFToken')
    token = header_token

    if not token and request.is_json:
        token = (request.get_json(silent=True) or {}).get('csrf_token')
    if not token:
        token = request.form.get('csrf_token')

    if not token or not hmac.compare_digest(str(token), str(session_token)):
        if is_api:
            return jsonify({'error': 'csrf_missing_or_invalid'}), 403
        return ('Forbidden', 403)

    return None


@app.before_request
def _enforce_https():
    if not PRODUCTION:
        return None
    if request.is_secure:
        return None
    if (request.path or '') == '/healthz':
        return None
    url = request.url
    if url.startswith('http://'):
        return redirect('https://' + url[len('http://'):], code=308)
    return None


@app.after_request
def _add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    path = request.path or ''
    if path.startswith('/static/'):
        if PRODUCTION:
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    if path in ('/chats', '/service-worker.js'):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    if PRODUCTION:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def _ensure_db_create_all() -> None:
    """Best-effort DB initialization for entrypoints that don't call __main__.

    - `python app.py` already initializes in __main__ (kept for clarity)
    - `flask run` / external WSGI import `app` and would otherwise skip create_all
    """
    try:
        with app.app_context():
            default_create = "0" if PRODUCTION else "1"
            if os.environ.get("LINKUP_CREATE_TABLES", default_create) == "1":
                db.create_all()
    except Exception:
        return


@app.route('/manifest.webmanifest')
def manifest_webmanifest():
    return send_from_directory(app.static_folder, 'manifest.webmanifest', mimetype='application/manifest+json')


@app.route('/service-worker.js')
def service_worker_js():
    return send_from_directory(app.static_folder, 'service-worker.js', mimetype='application/javascript')

# ------------------ Built-in AI bot ------------------

NOVA_USERNAME = 'NOVA'
NOVA_EMAIL = 'nova-bot@linkup.local'
NOVA_ENABLED = os.environ.get('NOVA_ENABLED', '1').strip().lower() not in ('0', 'false', 'no', 'off')

# ------------------ MODEL ------------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(15), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    email_verified = db.Column(db.Boolean, nullable=False, default=False)
    onboarding_seen = db.Column(db.Boolean, nullable=False, default=False)
    display_name = db.Column(db.String(40), nullable=True)
    about = db.Column(db.String(140), nullable=True)
    avatar_color = db.Column(db.String(16), nullable=True)
    avatar_filename = db.Column(db.String(120), nullable=True)
    last_seen_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<User {self.username}>"


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    attachment_filename = db.Column(db.String(140), nullable=True)
    attachment_original = db.Column(db.String(140), nullable=True)
    attachment_mime = db.Column(db.String(60), nullable=True)
    attachment_size = db.Column(db.Integer, nullable=True)
    reply_to_id = db.Column(db.Integer, nullable=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    deleted_for_all = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


class UserMedia(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    kind = db.Column(db.String(16), nullable=False)  # gif|sticker
    title = db.Column(db.String(80), nullable=True)
    filename = db.Column(db.String(140), nullable=False)
    mime = db.Column(db.String(60), nullable=False)
    size = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


class GlobalEmoji(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emoji = db.Column(db.String(16), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


class GroupMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    reply_to_id = db.Column(db.Integer, nullable=True)
    edited_at = db.Column(db.DateTime, nullable=True)
    deleted_for_all = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


class ContactRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    addressee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(12), nullable=False, default='pending')  # pending|accepted
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('requester_id', 'addressee_id', name='uq_contact_request_pair'),
    )


class SupportTicket(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category = db.Column(db.String(20), nullable=False, default='general')
    subject = db.Column(db.String(80), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(16), nullable=False, default='open')  # open|in_progress|closed
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


class MessageDeletion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'message_id', name='uq_message_deletion_user_message'),
    )


class MessageStar(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'message_id', name='uq_message_star_user_message'),
    )


class MessagePin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'message_id', name='uq_message_pin_user_message'),
    )


class DirectChatState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    other_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    last_read_message_id = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'other_user_id', name='uq_direct_chat_state_user_other'),
    )


class GroupChatState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    last_read_message_id = db.Column(db.Integer, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'group_id', name='uq_group_chat_state_user_group'),
    )


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    image_filename = db.Column(db.String(140), nullable=True)
    image_locked = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


class GroupMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(16), nullable=False, default='member')  # admin|member
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'user_id', name='uq_group_member_pair'),
    )


class GroupInvite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    inviter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    invitee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(12), nullable=False, default='pending')  # pending|accepted|declined
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('group_id', 'invitee_id', name='uq_group_invite_group_invitee'),
    )


class GroupPoll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    kind = db.Column(db.String(16), nullable=False)  # invite|remove|image_lock|image_remove
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    target_username = db.Column(db.String(15), nullable=True)
    status = db.Column(db.String(12), nullable=False, default='open')  # open|approved|rejected
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)
    decided_at = db.Column(db.DateTime, nullable=True)


class GroupPollVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('group_poll.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    vote = db.Column(db.String(8), nullable=False)  # yes|no
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('poll_id', 'user_id', name='uq_group_poll_vote_poll_user'),
    )


class OAuthAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(32), nullable=False)
    provider_user_id = db.Column(db.String(128), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)

    __table_args__ = (
        db.UniqueConstraint('provider', 'provider_user_id', name='uq_oauth_provider_user'),
    )


class EmailOTP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


class EmailVerifyOTP(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed_at = db.Column(db.DateTime, nullable=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    ip = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_utcnow)


# Create tables early for entrypoints like `flask run`.
_ensure_db_create_all()


def _ensure_chat_state_tables() -> None:
    try:
        with app.app_context():
            DirectChatState.__table__.create(bind=db.engine, checkfirst=True)
            GroupChatState.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        return


_ensure_chat_state_tables()


def _ensure_user_media_table() -> None:
    try:
        with app.app_context():
            UserMedia.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        return


_ensure_user_media_table()


def _ensure_global_emoji_table() -> None:
    try:
        with app.app_context():
            GlobalEmoji.__table__.create(bind=db.engine, checkfirst=True)
    except Exception:
        return


_ensure_global_emoji_table()


def _get_me():
    user_id = session.get('user_id')
    if not user_id:
        return None
    return _db_get(User, user_id)


def _is_user_online(user: User | None, now: datetime | None = None) -> bool:
    if not user:
        return False
    last_seen = getattr(user, 'last_seen_at', None)
    if not last_seen:
        return False
    if not now:
        now = _utcnow()
    try:
        return (now - last_seen).total_seconds() <= _presence_window_seconds()
    except Exception:
        return False


def _presence_payload_for(user: User | None) -> dict:
    if not user:
        return {'is_online': False, 'last_seen_at': ''}
    now = _utcnow()
    last_seen = getattr(user, 'last_seen_at', None)
    return {
        'is_online': _is_user_online(user, now=now),
        'last_seen_at': (last_seen.isoformat() + 'Z') if last_seen else '',
    }


def _touch_last_seen(user: User | None, now: datetime | None = None) -> bool:
    if not user:
        return False
    if not now:
        now = _utcnow()
    last_seen = getattr(user, 'last_seen_at', None)
    try:
        if last_seen and (now - last_seen).total_seconds() < 15:
            return False
    except Exception:
        pass
    user.last_seen_at = now
    try:
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        return False


def _get_csrf_token() -> str:
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


@app.context_processor
def _inject_csrf_token():
    return {'csrf_token': _get_csrf_token()}


def _contact_request_between(a_id: int, b_id: int):
    return (
        ContactRequest.query
        .filter(
            db.or_(
                db.and_(ContactRequest.requester_id == a_id, ContactRequest.addressee_id == b_id),
                db.and_(ContactRequest.requester_id == b_id, ContactRequest.addressee_id == a_id),
            )
        )
        .first()
    )


def _is_accepted_contact(a_id: int, b_id: int) -> bool:
    req = _contact_request_between(a_id, b_id)
    return bool(req and req.status == 'accepted')


def _get_direct_chat_state(user_id: int, other_user_id: int, create: bool = False) -> DirectChatState | None:
    state = DirectChatState.query.filter_by(user_id=int(user_id), other_user_id=int(other_user_id)).first()
    if state or not create:
        return state
    state = DirectChatState(user_id=int(user_id), other_user_id=int(other_user_id))
    db.session.add(state)
    return state


def _get_group_chat_state(user_id: int, group_id: int, create: bool = False) -> GroupChatState | None:
    state = GroupChatState.query.filter_by(user_id=int(user_id), group_id=int(group_id)).first()
    if state or not create:
        return state
    state = GroupChatState(user_id=int(user_id), group_id=int(group_id))
    db.session.add(state)
    return state


def _mark_direct_chat_read(user_id: int, other_user_id: int, latest_message_id: int | None) -> None:
    if not latest_message_id:
        return
    state = _get_direct_chat_state(user_id, other_user_id, create=True)
    if not state:
        return
    current = int(state.last_read_message_id or 0)
    latest = int(latest_message_id)
    if latest <= current:
        return
    state.last_read_message_id = latest
    state.updated_at = _utcnow()
    db.session.commit()


def _mark_group_chat_read(user_id: int, group_id: int, latest_message_id: int | None) -> None:
    if not latest_message_id:
        return
    state = _get_group_chat_state(user_id, group_id, create=True)
    if not state:
        return
    current = int(state.last_read_message_id or 0)
    latest = int(latest_message_id)
    if latest <= current:
        return
    state.last_read_message_id = latest
    state.updated_at = _utcnow()
    db.session.commit()


def _message_preview_text(stored: str, attachment_name: str | None = None, deleted_for_all: bool = False) -> str:
    if deleted_for_all:
        return 'Message deleted'
    text = _safe_decrypt_message_content(stored).strip() if stored else ''
    if text:
        return text[:120]
    if attachment_name:
        return f"[Attachment: {attachment_name}]"
    return ''


def _is_group_member(user_id: int, group_id: int) -> bool:
    try:
        gm = GroupMember.query.filter_by(group_id=int(group_id), user_id=int(user_id)).first()
        return bool(gm)
    except Exception:
        return False


def _group_member_ids(group_id: int) -> list[int]:
    try:
        return [gm.user_id for gm in GroupMember.query.filter_by(group_id=int(group_id)).all()]
    except Exception:
        return []


def _poll_counts(poll_id: int, exclude_user_id: int | None = None) -> tuple[int, int]:
    yes = 0
    no = 0
    ex = int(exclude_user_id) if exclude_user_id is not None else None
    for v in GroupPollVote.query.filter_by(poll_id=int(poll_id)).all():
        if ex is not None and int(v.user_id) == ex:
            continue
        if (v.vote or '') == 'yes':
            yes += 1
        elif (v.vote or '') == 'no':
            no += 1
    return yes, no


def _poll_excluded_subject_user_id(poll: GroupPoll) -> int | None:
    """Return a user_id to exclude from eligible voters for this poll.

    For removal polls, the subject (target member) should not be asked to vote and
    should not be counted toward totals.
    """
    try:
        if not poll or (poll.kind or '') != 'remove':
            return None
        if poll.target_user_id:
            return int(poll.target_user_id)
        # Fallback: resolve by username if needed.
        if poll.target_username:
            u = User.query.filter(db.func.lower(User.username) == str(poll.target_username).lower()).first()
            return int(u.id) if u else None
        return None
    except Exception:
        return None


def _poll_eligible_member_ids(poll: GroupPoll) -> list[int]:
    ids = _group_member_ids(poll.group_id)
    ex = _poll_excluded_subject_user_id(poll)
    if ex is None:
        return ids
    return [uid for uid in ids if int(uid) != int(ex)]


def _poll_finalize_if_needed(poll: GroupPoll) -> dict:
    """Evaluate poll and, if decided, execute the action and mark status."""
    if not poll or (poll.status or '') != 'open':
        return {'decided': False}

    member_ids = _poll_eligible_member_ids(poll)
    total = len(member_ids)
    ex = _poll_excluded_subject_user_id(poll)
    yes, no = _poll_counts(poll.id, exclude_user_id=ex)

    # majority yes means strictly more than half of current members
    majority = (total // 2) + 1
    decided = False
    outcome = None

    if yes >= majority:
        decided = True
        outcome = 'approved'
    elif (yes + no) >= total and yes < majority:
        decided = True
        outcome = 'rejected'

    if not decided:
        return {'decided': False, 'yes': yes, 'no': no, 'total': total}

    poll.status = outcome
    poll.decided_at = _utcnow()

    # Execute action on approval.
    if outcome == 'approved':
        if poll.kind == 'invite':
            target = None
            if poll.target_user_id:
                target = _db_get(User, int(poll.target_user_id))
            elif poll.target_username:
                target = User.query.filter(db.func.lower(User.username) == str(poll.target_username).lower()).first()
            if target:
                # Already member?
                if not GroupMember.query.filter_by(group_id=int(poll.group_id), user_id=int(target.id)).first():
                    existing = GroupInvite.query.filter_by(group_id=int(poll.group_id), invitee_id=int(target.id)).first()
                    if existing and existing.status == 'pending':
                        pass
                    else:
                        inv = GroupInvite(group_id=int(poll.group_id), inviter_id=int(poll.created_by_id), invitee_id=int(target.id), status='pending')
                        db.session.add(inv)
        elif poll.kind == 'remove':
            target = None
            if poll.target_user_id:
                target = _db_get(User, int(poll.target_user_id))
            elif poll.target_username:
                target = User.query.filter(db.func.lower(User.username) == str(poll.target_username).lower()).first()
            if target:
                gm = GroupMember.query.filter_by(group_id=int(poll.group_id), user_id=int(target.id)).first()
                if gm:
                    db.session.delete(gm)
        elif poll.kind == 'image_lock':
            g = _db_get(Group, int(poll.group_id))
            if g and getattr(g, 'image_filename', None):
                g.image_locked = True
        elif poll.kind == 'image_remove':
            g = _db_get(Group, int(poll.group_id))
            if g and getattr(g, 'image_filename', None):
                _delete_group_image_file(g)
                g.image_filename = None
                g.image_locked = False

    db.session.commit()
    _delete_group_if_empty(int(poll.group_id))
    return {'decided': True, 'status': poll.status, 'yes': yes, 'no': no, 'total': total}


def _delete_group_if_empty(group_id: int) -> None:
    """If a group has zero members, delete the group and all related rows."""
    try:
        remaining = GroupMember.query.filter_by(group_id=int(group_id)).count()
        if int(remaining or 0) > 0:
            return
        _delete_group_cascade(int(group_id))
        db.session.commit()
    except Exception:
        db.session.rollback()


def _delete_group_cascade(group_id: int) -> None:
    """Manual cascade delete for SQLite."""
    # Delete poll votes first.
    poll_ids = [p.id for p in GroupPoll.query.filter_by(group_id=int(group_id)).all()]
    if poll_ids:
        GroupPollVote.query.filter(GroupPollVote.poll_id.in_(poll_ids)).delete(synchronize_session=False)
    GroupPoll.query.filter_by(group_id=int(group_id)).delete(synchronize_session=False)
    GroupMessage.query.filter_by(group_id=int(group_id)).delete(synchronize_session=False)
    GroupInvite.query.filter_by(group_id=int(group_id)).delete(synchronize_session=False)
    GroupMember.query.filter_by(group_id=int(group_id)).delete(synchronize_session=False)
    g = _db_get(Group, int(group_id))
    if g:
        _delete_group_image_file(g)
        db.session.delete(g)


def _delete_group_image_file(group: Group) -> None:
    try:
        fn = getattr(group, 'image_filename', None)
        if not fn:
            return
        p = _group_avatars_dir() / fn
        if p.exists():
            p.unlink()
    except Exception:
        return


def _delete_contact_relation(a_id: int, b_id: int) -> int:
    """Delete any ContactRequest row between two users. Returns number deleted (0/1)."""
    rel = _contact_request_between(a_id, b_id)
    if not rel:
        return 0
    db.session.delete(rel)
    return 1


def _ensure_user_profile_columns() -> None:
    """Best-effort SQLite migration for existing installs (no Alembic)."""
    try:
        with app.app_context():
            cols = [r[1] for r in db.session.execute(text('PRAGMA table_info(user)')).fetchall()]
            if not cols:
                return

            alters: list[str] = []
            if 'display_name' not in cols:
                alters.append('ALTER TABLE user ADD COLUMN display_name VARCHAR(40)')
            if 'about' not in cols:
                alters.append('ALTER TABLE user ADD COLUMN about VARCHAR(140)')
            if 'avatar_color' not in cols:
                alters.append('ALTER TABLE user ADD COLUMN avatar_color VARCHAR(16)')
            if 'avatar_filename' not in cols:
                alters.append('ALTER TABLE user ADD COLUMN avatar_filename VARCHAR(120)')

            for stmt in alters:
                db.session.execute(text(stmt))
            if alters:
                db.session.commit()
    except Exception:
        # Ignore if DB isn't initialized yet or migration fails.
        return


def _ensure_group_image_columns() -> None:
    """Best-effort SQLite migration for group image fields."""
    try:
        with app.app_context():
            cols = [r[1] for r in db.session.execute(text('PRAGMA table_info(group)')).fetchall()]
            if not cols:
                return

            alters: list[str] = []
            if 'image_filename' not in cols:
                alters.append('ALTER TABLE "group" ADD COLUMN image_filename VARCHAR(140)')
            if 'image_locked' not in cols:
                alters.append('ALTER TABLE "group" ADD COLUMN image_locked INTEGER NOT NULL DEFAULT 0')

            for stmt in alters:
                db.session.execute(text(stmt))
            if alters:
                db.session.commit()
    except Exception:
        return


def _ensure_message_attachment_columns() -> None:
    """Best-effort SQLite migration for existing installs (no Alembic)."""
    try:
        with app.app_context():
            cols = [r[1] for r in db.session.execute(text('PRAGMA table_info(message)')).fetchall()]
            if not cols:
                return

            alters: list[str] = []
            if 'attachment_filename' not in cols:
                alters.append('ALTER TABLE message ADD COLUMN attachment_filename VARCHAR(140)')
            if 'attachment_original' not in cols:
                alters.append('ALTER TABLE message ADD COLUMN attachment_original VARCHAR(140)')
            if 'attachment_mime' not in cols:
                alters.append('ALTER TABLE message ADD COLUMN attachment_mime VARCHAR(60)')
            if 'attachment_size' not in cols:
                alters.append('ALTER TABLE message ADD COLUMN attachment_size INTEGER')

            for stmt in alters:
                db.session.execute(text(stmt))
            if alters:
                db.session.commit()
    except Exception:
        return


def _ensure_message_action_columns() -> None:
    """Best-effort SQLite migration for existing installs (no Alembic)."""
    try:
        with app.app_context():
            cols = [r[1] for r in db.session.execute(text('PRAGMA table_info(message)')).fetchall()]
            if not cols:
                return

            alters: list[str] = []
            if 'edited_at' not in cols:
                alters.append('ALTER TABLE message ADD COLUMN edited_at DATETIME')
            if 'deleted_for_all' not in cols:
                alters.append('ALTER TABLE message ADD COLUMN deleted_for_all INTEGER NOT NULL DEFAULT 0')
            if 'reply_to_id' not in cols:
                alters.append('ALTER TABLE message ADD COLUMN reply_to_id INTEGER')

            for stmt in alters:
                db.session.execute(text(stmt))
            if alters:
                db.session.commit()
    except Exception:
        return


def _ensure_user_email_verified_column() -> None:
    """Best-effort SQLite migration for existing installs (no Alembic)."""
    try:
        with app.app_context():
            cols = [r[1] for r in db.session.execute(text('PRAGMA table_info(user)')).fetchall()]
            if not cols:
                return

            if 'email_verified' in cols:
                return

            db.session.execute(text('ALTER TABLE user ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0'))
            db.session.commit()
    except Exception:
        return


def _ensure_user_onboarding_seen_column() -> None:
    try:
        with app.app_context():
            cols = {r[1] for r in db.session.execute(text('PRAGMA table_info(user)')).fetchall()}
            if 'onboarding_seen' in cols:
                return
            db.session.execute(text('ALTER TABLE user ADD COLUMN onboarding_seen INTEGER NOT NULL DEFAULT 0'))
            db.session.commit()
    except Exception:
        return


def _ensure_user_presence_column() -> None:
    try:
        with app.app_context():
            cols = {r[1] for r in db.session.execute(text('PRAGMA table_info(user)')).fetchall()}
            if 'last_seen_at' in cols:
                return
            db.session.execute(text('ALTER TABLE user ADD COLUMN last_seen_at DATETIME'))
            db.session.commit()
    except Exception:
        return


# Best-effort: add new columns for existing SQLite DBs.
_ensure_user_profile_columns()
_ensure_group_image_columns()
_ensure_message_attachment_columns()
_ensure_message_action_columns()
_ensure_user_email_verified_column()
_ensure_user_onboarding_seen_column()
_ensure_user_presence_column()


def _is_nova_username(username: str) -> bool:
    return (username or '').strip().lower() == NOVA_USERNAME.lower()


def _get_or_create_nova_user() -> Optional[User]:
    """Ensure the built-in NOVA bot account exists.

    Best-effort: returns None if DB isn't ready yet.
    """
    try:
        with app.app_context():
            u = User.query.filter(db.func.lower(User.username) == NOVA_USERNAME.lower()).first()
            if u:
                # Keep the canonical casing stable.
                if u.username != NOVA_USERNAME:
                    u.username = NOVA_USERNAME
                    db.session.commit()
                return u

            # Create a non-loginable bot user (random password hash).
            bot = User(
                username=NOVA_USERNAME,
                password=generate_password_hash(os.urandom(32).hex()),
                email=NOVA_EMAIL,
                email_verified=True,
                display_name='NOVA',
                about='AI assistant',
                avatar_color='#7c3aed',
            )
            db.session.add(bot)
            db.session.commit()
            return bot
    except Exception:
        return None


def _nova_generate_reply(user_text: str, me: User) -> str:
    """Rule-based fallback bot.

    This keeps the project runnable without external AI keys.
    """
    t = (user_text or '').strip()
    low = t.lower()
    if not t:
        return "Say something and I'll help. Try /help."

    # Try a real LLM provider first (if configured). Caller supplies history.
    # NOTE: We keep this function as the offline fallback.

    # Friendly basics
    if low in ('hi', 'hello', 'hey', 'yo', 'hola', 'hii', 'hiii'):
        return (
            "Hi! I'm NOVA — your LinkUp assistant.\n"
            "Ask me anything, or type /help for commands."
        )

    if (
        low in ('what is your name', "what's your name", 'your name', 'who are you', 'name?')
        or ('your name' in low)
        or ('who are you' in low)
    ):
        return (
            "My name is NOVA.\n"
            "If you want smarter answers, configure a provider (OpenAI/Ollama/custom). Otherwise I reply in offline mode."
        )

    if (
        low in ('what is linkup', 'what is link up', "what's linkup", "what's link up")
        or low.startswith('what is linkup')
        or low.startswith('what is link up')
    ):
        return (
            "LinkUp is a Flask + SQLite chat app with:\n"
            "• Contact-request handshake (no unsolicited DMs)\n"
            "• Encrypted-at-rest messages (stored encrypted in SQLite)\n"
            "• Group chats with majority-vote polls for inviting/removing members\n"
            "• NOVA: a built-in assistant (offline by default; can connect to LLMs)\n\n"
            "If you tell me what you want to do (add contact, create group, fix an error), I’ll guide you."
        )

    if ('what kind of reply' in low) or ('why are you replying' in low) or ('this reply' in low and 'weird' in low):
        return (
            "Right now I'm running in offline fallback mode (no LLM configured), so I only do simple rule-based replies.\n"
            "To enable your custom neural network/NLP: set NOVA_PROVIDER=python or NOVA_PROVIDER=http (see README)."
        )

    if low in ('/help', 'help', 'commands') or low.startswith('/help '):
        return (
            "Hi — I'm NOVA.\n\n"
            "Commands:\n"
            "• /help — show this\n"
            "• /linkup — LinkUp help topics\n"
            "• /about — what I can do\n"
            "• /privacy — how data is handled\n\n"
            "Tip: Ask me about LinkUp features, encryption, or how to do something."
        )

    if low in ('/linkup', 'linkup', 'link up', 'linkup help') or low.startswith('/linkup '):
        return (
            "LinkUp help (common topics):\n"
            "• Add a contact: New chat → request username → they Accept in Requests\n"
            "• Requests: Menu (left dock) → Chat requests / Group invites\n"
            "• Create group: left dock Group → name → invite contacts\n"
            "• Group options: open a group → ⋮ → Group options\n"
            "• Add/remove members: Group options → vote (poll) → majority decides\n"
            "• Remove contact: chat ⋮ → Remove contact\n"
            "• Encryption key: set CHAT_ENC_KEY (generate: python3 -m crypto gen-key)"
        )

    if low in ('/about', 'about') or low.startswith('/about '):
        return (
            "I'm NOVA — a built-in assistant for LinkUp. "
            "Right now I'm a lightweight offline bot (no external AI calls). "
            "If you wire a real LLM later, I can become a full AI agent."
        )

    if low in ('/privacy', 'privacy') or low.startswith('/privacy '):
        return (
            "Privacy note: messages are stored encrypted at rest in SQLite (see crypto.py). "
            "This NOVA bot runs inside your server process; it doesn't send your messages anywhere "
            "unless you later configure an external AI provider."
        )

    if any(k in low for k in ('encrypt', 'encryption', 'crypto', 'key', 'chat_enc_key')):
        return (
            "LinkUp encrypts message content before storing it in the DB. "
            "Set CHAT_ENC_KEY to a stable key so messages remain decryptable across restarts. "
            "Generate one with: python3 -m crypto gen-key"
        )

    # Offline LinkUp feature Q&A (simple keyword routing)
    if any(k in low for k in ('linkup', 'link up', 'request', 'requests', 'contact', 'group', 'invite', 'poll', 'vote', 'nova', 'server.sh', 'chat_enc_key', 'encryption')):
        if any(k in low for k in ('run', 'start', 'server', 'serve', 'localhost', 'port', 'server.sh')):
            return (
                "To run LinkUp locally:\n"
                "1) Run: ./server.sh\n"
                "2) Open: http://127.0.0.1:8000\n\n"
                "Tip: Set CHAT_ENC_KEY for stable encryption (python3 -m crypto gen-key)."
            )

        if any(k in low for k in ('add contact', 'new chat', 'request user', 'request username', 'connect')):
            return (
                "To add a contact (handshake):\n"
                "- Click New chat → enter username → Send request\n"
                "- They must Accept in Menu → Chat requests\n"
                "After acceptance, you can message each other."
            )

        if any(k in low for k in ('requests', 'inbox', 'accept', 'reject', 'withdraw', 'pending')):
            return (
                "Requests are in Menu (left dock) → Chat requests / Group invites.\n"
                "- Incoming: Accept or Reject\n"
                "- Sent: Withdraw (if pending)"
            )

        if any(k in low for k in ('create group', 'make a group', 'new group')):
            return (
                "To create a group:\n"
                "- Use the left dock Group button\n"
                "- Choose a group name\n"
                "- Invite contacts (initial creation invites can be sent immediately)"
            )

        if any(k in low for k in ('group options', 'members', 'invite', 'remove member', 'exit group', 'poll')):
            return (
                "Group management:\n"
                "- Open a group chat → ⋮ → Group options\n"
                "- Add/remove members uses Yes/No polls (majority decides)\n"
                "- Removal polls exclude the subject from voting\n"
                "- Exit group is always allowed"
            )

        if any(k in low for k in ('nova', 'ai', 'assistant', 'openai', 'ollama', 'provider')):
            return (
                "NOVA runs offline by default. To connect a real model, set env vars and restart. Examples:\n"
                "- OpenAI: NOVA_PROVIDER=openai + OPENAI_API_KEY\n"
                "- Ollama: NOVA_PROVIDER=ollama + OLLAMA_MODEL\n"
                "Docs are in README.md under 'Built-in AI assistant (NOVA)'."
            )

        # Generic LinkUp overview if the user asked something LinkUp-related but not a specific topic.
        return (
            "LinkUp quick overview:\n"
            "• Chats are unlocked after a request is Accepted\n"
            "• Messages are encrypted at rest (set CHAT_ENC_KEY for stability)\n"
            "• Groups use polls (majority vote) for invites/removals\n"
            "• Menu/Settings/Group actions are in the left dock\n\n"
            "Ask me a specific question like: 'how to add contact', 'where are requests', 'how do polls work', or '/linkup'."
        )

    if low.startswith('how do i ') or low.startswith('how to ') or low.startswith('how can i '):
        return (
            f"Got it, {me.username}. Tell me what you're trying to achieve and what you've tried so far. "
            "If it's a LinkUp feature, mention the screen (Chats / New chat / Menu) and I’ll walk you through it."
        )

    # Default: short, friendly, and safe.
    snippet = t if len(t) <= 280 else (t[:277] + '…')
    return (
        "I’m here. If you want, paste the exact error/output or describe the goal in one sentence.\n\n"
        f"You said: \"{snippet}\""
    )


def _nova_history_for_user(me: User, nova: User, limit: int = 18):
    """Build short conversation history for LLM context."""
    try:
        lim = int(limit)
    except Exception:
        lim = 18

    q = (
        Message.query
        .filter(
            db.or_(
                db.and_(Message.sender_id == me.id, Message.recipient_id == nova.id),
                db.and_(Message.sender_id == nova.id, Message.recipient_id == me.id),
            )
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(max(0, lim))
    )

    rows = list(reversed(q.all()))
    out = []
    for m in rows:
        if getattr(m, 'deleted_for_all', False):
            continue
        role = 'assistant' if m.sender_id == nova.id else 'user'
        txt = _safe_decrypt_message_content(m.content)
        if m.attachment_filename and not txt:
            txt = f"[Attachment: {m.attachment_original or 'file'}]"
        if txt:
            out.append({'role': role, 'content': txt})
    return out


def _email_token_serializer() -> URLSafeTimedSerializer:
    secret = app.secret_key or 'dev-secret-key-change-me'
    return URLSafeTimedSerializer(secret_key=secret)


def _group_token_serializer() -> URLSafeTimedSerializer:
    secret = app.secret_key or 'dev-secret-key-change-me'
    return URLSafeTimedSerializer(secret_key=secret)


def _make_group_creation_token(group_id: int, owner_id: int) -> str:
    s = _group_token_serializer()
    return s.dumps({'gid': int(group_id), 'uid': int(owner_id)}, salt='group-create')


def _load_group_creation_token(token: str, max_age_seconds: int = 10 * 60) -> dict:
    s = _group_token_serializer()
    return s.loads(token, salt='group-create', max_age=max_age_seconds)


def _make_email_verify_token(user: User) -> str:
    s = _email_token_serializer()
    return s.dumps({'uid': int(user.id), 'email': (user.email or '').lower()}, salt='verify-email')


def _load_email_verify_token(token: str, max_age_seconds: int = 24 * 60 * 60) -> dict:
    s = _email_token_serializer()
    return s.loads(token, salt='verify-email', max_age=max_age_seconds)


def _send_email(to_email: str, subject: str, body_text: str) -> bool:
    provider = (os.environ.get('SMTP_PROVIDER') or '').strip().lower()
    host = (os.environ.get('SMTP_HOST') or '').strip()
    port_raw = (os.environ.get('SMTP_PORT') or '').strip()
    user = (os.environ.get('SMTP_USER') or '').strip()
    password = (os.environ.get('SMTP_PASS') or '').strip()
    from_email = (os.environ.get('SMTP_FROM') or user or '').strip()

    # Convenience presets for common providers.
    # You can still override everything via SMTP_HOST/SMTP_PORT/SMTP_USER.
    if not host and provider in ('gmail', 'google'):
        host = 'smtp.gmail.com'
    elif not host and provider in ('outlook', 'office365', 'microsoft'):
        host = 'smtp.office365.com'
    elif not host and provider in ('sendgrid',):
        host = 'smtp.sendgrid.net'
        if not user:
            user = 'apikey'
            if not from_email:
                from_email = user

    try:
        port = int(port_raw or '587')
    except Exception:
        port = 587

    # If SMTP isn't configured, log to console for dev.
    if not host or not from_email:
        print('--- EMAIL (DEV MODE) ---')
        print('To:', to_email)
        print('Subject:', subject)
        print(body_text)
        print('------------------------')
        return False

    msg = EmailMessage()
    msg['From'] = from_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.set_content(body_text)

    try:
        with smtplib.SMTP(host, port, timeout=12) as server:
            server.ehlo()
            try:
                server.starttls()
                server.ehlo()
            except Exception:
                # allow non-TLS servers (not recommended)
                pass
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        return True
    except Exception:
        logging.getLogger('mail').exception('SMTP send failed')
        return False


def _smtp_configured() -> bool:
    host = (os.environ.get('SMTP_HOST') or '').strip()
    user = (os.environ.get('SMTP_USER') or '').strip()
    from_email = (os.environ.get('SMTP_FROM') or user or '').strip()
    return bool(host and from_email)


def _email_verification_required() -> bool:
    # In production, default to ON unless explicitly disabled.
    raw = os.environ.get('EMAIL_VERIFY_REQUIRED')
    if raw is None:
        return bool(PRODUCTION)
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


def _otp_verify_ttl_seconds() -> int:
    try:
        return int(os.environ.get('VERIFY_OTP_TTL_SECONDS') or os.environ.get('OTP_TTL_SECONDS') or '600')
    except Exception:
        return 600


def _client_ip() -> str:
    return (request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or '')[:64]


def _send_verification_otp(user: User) -> tuple[bool, str | None]:
    code = str(secrets.randbelow(1000000)).zfill(6)
    otp = EmailVerifyOTP(
        user_id=int(user.id),
        email=_normalize_email(user.email),
        code_hash=generate_password_hash(code),
        expires_at=_utcnow() + timedelta(seconds=_otp_verify_ttl_seconds()),
        ip=_client_ip(),
        user_agent=(request.headers.get('User-Agent') or '')[:200],
    )
    db.session.add(otp)
    db.session.commit()

    subject = 'LinkUp: verify your email'
    body = (
        f"Hi {user.username},\n\n"
        "Your LinkUp email verification code is:\n\n"
        f"{code}\n\n"
        f"This code expires in {_otp_verify_ttl_seconds() // 60} minutes.\n"
    )
    sent = _send_email(user.email, subject, body)
    dev_code = None
    if (not PRODUCTION) and (not sent) and (not _smtp_configured()):
        dev_code = code
    return bool(sent), dev_code


# In production, do not allow a "verification required" deployment without SMTP.
if PRODUCTION and _email_verification_required() and not _smtp_configured():
    raise RuntimeError("SMTP must be configured when EMAIL_VERIFY_REQUIRED is enabled")


def _send_verification_email(user: User) -> bool:
    token = _make_email_verify_token(user)
    verify_url = url_for('verify_email', token=token, _external=True)
    subject = 'LinkUp: verify your email'
    body = (
        f"Hi {user.username},\n\n"
        "Thanks for registering on LinkUp. Please verify your email to activate your account:\n\n"
        f"{verify_url}\n\n"
        "This link expires in 24 hours. If you didn’t create this account, you can ignore this email.\n"
    )
    return _send_email(user.email, subject, body)


def _avatars_dir() -> Path:
    return Path(app.root_path) / 'static' / 'avatars'


def _group_avatars_dir() -> Path:
    return Path(app.root_path) / 'static' / 'group_avatars'


def _uploads_dir() -> Path:
    return Path(app.instance_path) / 'uploads'


def _media_dir() -> Path:
    return _uploads_dir() / 'media'


def _avatar_url(user: User | None) -> str:
    if not user or not getattr(user, 'avatar_filename', None):
        return ''
    return url_for('static', filename=f"avatars/{user.avatar_filename}")


def _group_avatar_url(group: Group | None) -> str:
    if not group or not getattr(group, 'image_filename', None):
        return ''
    return url_for('static', filename=f"group_avatars/{group.image_filename}")


def _allowed_avatar_ext(filename: str) -> str | None:
    name = (filename or '').lower()
    for ext in ('.png', '.jpg', '.jpeg', '.webp'):
        if name.endswith(ext):
            return ext
    return None


def _allowed_group_image_ext(filename: str) -> str | None:
    return _allowed_avatar_ext(filename)


def _file_size_bytes(f) -> int:
    try:
        pos = f.stream.tell()
        f.stream.seek(0, os.SEEK_END)
        size = int(f.stream.tell())
        f.stream.seek(pos)
        return size
    except Exception:
        return -1


def _attachment_url(m: Message) -> str:
    if not m or not getattr(m, 'attachment_filename', None):
        return ''
    return url_for('download_upload', filename=m.attachment_filename)


@app.route('/uploads/<path:filename>')
def download_upload(filename: str):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    filename = (filename or '').strip()
    if not filename:
        return jsonify({'error': 'missing_file'}), 400

    msg = Message.query.filter_by(attachment_filename=filename).first()
    if not msg:
        return jsonify({'error': 'not_found'}), 404

    if getattr(msg, 'deleted_for_all', False):
        return jsonify({'error': 'not_found'}), 404

    if me.id not in (msg.sender_id, msg.recipient_id):
        return jsonify({'error': 'forbidden'}), 403

    base_dir = _uploads_dir()
    path = base_dir / filename
    if not path.exists() and _is_media_file(filename):
        base_dir = _media_dir()
        path = base_dir / filename
    if not path.exists():
        return jsonify({'error': 'not_found'}), 404

    # Let images/PDF render in-browser; user can still save from UI.
    return send_from_directory(
        str(base_dir),
        filename,
        as_attachment=False,
        download_name=(msg.attachment_original or filename),
    )


@app.route('/api/media/<int:media_id>/file')
def download_media(media_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    media = _db_get(UserMedia, media_id)
    if not media:
        return jsonify({'error': 'not_found'}), 404
    if int(media.user_id) != int(me.id):
        return jsonify({'error': 'forbidden'}), 403

    path = _media_dir() / media.filename
    if not path.exists():
        return jsonify({'error': 'not_found'}), 404

    return send_from_directory(
        str(_media_dir()),
        media.filename,
        as_attachment=False,
        download_name=(media.title or media.filename),
        mimetype=(media.mime or None),
    )


def _allowed_attachment_ext(filename: str) -> str | None:
    name = (filename or '').lower()
    for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf', '.txt', '.zip'):
        if name.endswith(ext):
            return ext
    return None


def _allowed_media_kind(mime: str, filename: str) -> str | None:
    m = (mime or '').lower()
    name = (filename or '').lower()
    if m == 'image/gif' or name.endswith('.gif'):
        return 'gif'
    if any(name.endswith(ext) for ext in ('.png', '.webp', '.jpg', '.jpeg')):
        return 'sticker'
    if m.startswith('image/'):
        return 'sticker'
    return None


def _attachment_media_kind(mime: str, filename: str) -> str | None:
    m = (mime or '').lower()
    name = (filename or '').lower()
    if m == 'image/gif' or name.endswith('.gif'):
        return 'gif'
    if m in ('image/webp', 'image/png') or name.endswith('.webp') or name.endswith('.png'):
        return 'sticker'
    return None


def _save_user_media(me: User, kind: str, title: str, filename: str, mime: str, size: int) -> UserMedia:
    media = UserMedia(
        user_id=int(me.id),
        kind=(kind or 'sticker')[:16],
        title=(title or '')[:80],
        filename=filename,
        mime=(mime or '')[:60],
        size=int(size or 0),
    )
    db.session.add(media)
    db.session.commit()
    return media


def _media_response_payload(media: UserMedia) -> dict:
    return {
        'id': int(media.id),
        'kind': media.kind,
        'title': media.title or '',
        'url': url_for('download_media', media_id=int(media.id)),
        'mime': media.mime,
        'size': int(media.size or 0),
        'created_at': media.created_at.isoformat() if media.created_at else '',
    }


def _ensure_media_dir() -> None:
    try:
        _media_dir().mkdir(parents=True, exist_ok=True)
    except Exception:
        return


def _center_crop_square(img: Image.Image) -> Image.Image:
    w, h = img.size
    side = min(w, h)
    left = max(0, (w - side) // 2)
    top = max(0, (h - side) // 2)
    return img.crop((left, top, left + side, top + side))


def _draw_caption(img: Image.Image, caption: str) -> None:
    if not caption:
        return
    text = caption.strip()
    if not text:
        return
    text = text[:60]
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()
    pad = 6
    if hasattr(draw, 'textbbox'):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = (bbox[2] - bbox[0]) if bbox else 0
        th = (bbox[3] - bbox[1]) if bbox else 0
    else:
        tw, th = draw.textsize(text, font=font)
    x = max(pad, (img.size[0] - tw) // 2)
    y = max(pad, img.size[1] - th - pad)
    shadow = (0, 0, 0, 160)
    draw.text((x + 1, y + 1), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 230))


def _make_sticker(image: Image.Image, size: int, caption: str) -> Image.Image:
    base = image.convert('RGBA')
    base = _center_crop_square(base)
    base = base.resize((size, size), Image.LANCZOS)
    _draw_caption(base, caption)
    return base


def _auto_save_media_from_attachment(
    me: User,
    source_filename: str,
    original_name: str,
    mime: str,
    size: int | None,
) -> None:
    kind = _attachment_media_kind(mime, original_name)
    if kind not in ('gif', 'sticker'):
        return
    try:
        _ensure_media_dir()
        src = _uploads_dir() / source_filename
        if not src.exists():
            return
        stamp = int(_utcnow().timestamp())
        base = secure_filename(me.username) or f"user{me.id}"
        ext = '.gif' if kind == 'gif' else '.png'
        filename = f"{base}_{me.id}_{stamp}_{random.randint(1000,9999)}{ext}"
        dest = _media_dir() / filename
        shutil.copyfile(src, dest)
        final_size = int(dest.stat().st_size) if dest.exists() else int(size or 0)
        title = (Path(original_name).stem or kind)[:80]
        _save_user_media(me, kind, title, filename, (mime or ''), final_size)
    except Exception:
        return


def _is_media_file(filename: str | None) -> bool:
    if not filename:
        return False
    try:
        return UserMedia.query.filter_by(filename=filename).first() is not None
    except Exception:
        return False


def _is_emoji_codepoint(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch)
    return (
        0x1F300 <= cp <= 0x1FAFF
        or 0x1F100 <= cp <= 0x1F1FF
        or 0x2600 <= cp <= 0x26FF
        or 0x2700 <= cp <= 0x27BF
        or 0x2300 <= cp <= 0x23FF
        or 0xFE00 <= cp <= 0xFE0F
    )


def _is_regional_indicator(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch)
    return 0x1F1E6 <= cp <= 0x1F1FF


def _is_emoji_modifier(ch: str) -> bool:
    if not ch:
        return False
    cp = ord(ch)
    return 0x1F3FB <= cp <= 0x1F3FF


def _extract_emojis(text: str) -> list[str]:
    if not text:
        return []
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if _is_regional_indicator(ch) and i + 1 < n and _is_regional_indicator(text[i + 1]):
            out.append(ch + text[i + 1])
            i += 2
            continue
        if _is_emoji_codepoint(ch):
            seq = ch
            j = i + 1
            while j < n:
                nxt = text[j]
                if nxt == '\uFE0F' or nxt == '\u200D' or _is_emoji_modifier(nxt):
                    seq += nxt
                    j += 1
                    if nxt == '\u200D' and j < n:
                        seq += text[j]
                        j += 1
                    continue
                break
            out.append(seq)
            i = j
            continue
        i += 1
    # Preserve order, unique
    seen = set()
    uniq = []
    for e in out:
        if e in seen:
            continue
        seen.add(e)
        uniq.append(e)
    return uniq


def _save_global_emojis_from_text(text: str) -> None:
    emojis = _extract_emojis(text or '')
    if not emojis:
        return
    try:
        for e in emojis:
            exists = GlobalEmoji.query.filter_by(emoji=e).first()
            if exists:
                continue
            db.session.add(GlobalEmoji(emoji=e))
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return


def _tenor_api_key() -> str:
    return (os.environ.get('TENOR_API_KEY') or '').strip()


def _tenor_search(query: str, limit: int = 24) -> list[dict]:
    key = _tenor_api_key()
    if not key:
        raise RuntimeError('tenor_api_key_missing')

    q = (query or '').strip() or 'trending'
    try:
        lim = int(limit)
    except Exception:
        lim = 24
    lim = max(1, min(40, lim))

    params = {
        'key': key,
        'q': q,
        'limit': lim,
        'media_filter': 'gif,tinygif',
        'contentfilter': 'high',
    }
    r = requests.get('https://tenor.googleapis.com/v2/search', params=params, timeout=10)
    r.raise_for_status()
    data = r.json() or {}

    out = []
    for item in data.get('results', []) or []:
        media = item.get('media_formats') or {}
        gif = media.get('gif') or media.get('tinygif') or {}
        tiny = media.get('tinygif') or gif
        url = (gif.get('url') or '').strip()
        preview = (tiny.get('url') or url).strip()
        if not url:
            continue
        title = (item.get('content_description') or item.get('title') or 'GIF').strip()
        out.append({
            'id': str(item.get('id') or ''),
            'url': url,
            'preview': preview,
            'title': title,
        })
    return out[:lim]


def _is_allowed_gif_url(url: str) -> bool:
    try:
        u = urlparse(url or '')
        if u.scheme not in ('https',):
            return False
        host = (u.hostname or '').lower()
        return host.endswith('tenor.com')
    except Exception:
        return False


def _download_gif(url: str, filename: str, max_bytes: int = 10 * 1024 * 1024) -> tuple[bool, int | None, str | None]:
    try:
        r = requests.get(url, stream=True, timeout=12)
        if r.status_code != 200:
            return False, None, 'download_failed'
        ctype = (r.headers.get('Content-Type') or '').lower()
        if 'image/gif' not in ctype:
            return False, None, 'not_gif'
        path = _uploads_dir() / filename
        size = 0
        with open(path, 'wb') as fh:
            for chunk in r.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    try:
                        fh.close()
                    except Exception:
                        pass
                    try:
                        path.unlink(missing_ok=True)
                    except Exception:
                        pass
                    return False, None, 'file_too_large'
                fh.write(chunk)
        return True, size, None
    except Exception:
        try:
            (_uploads_dir() / filename).unlink(missing_ok=True)
        except Exception:
            pass
        return False, None, 'download_failed'


def _message_action_window_seconds() -> int:
    return 30


def _within_action_window(msg: Message) -> bool:
    try:
        now = _utcnow()
        age = (now - (msg.created_at or now)).total_seconds()
        return age <= _message_action_window_seconds()
    except Exception:
        return False


def _can_edit_message(me: User, msg: Message) -> bool:
    if not me or not msg:
        return False
    if msg.deleted_for_all:
        return False
    if msg.sender_id != me.id:
        return False
    return _within_action_window(msg)


def _can_delete_for_everyone(me: User, msg: Message) -> bool:
    if not me or not msg:
        return False
    if msg.deleted_for_all:
        return False
    if msg.sender_id != me.id:
        return False
    return _within_action_window(msg)


def _username_seed(raw: str) -> str:
    raw = (raw or '').strip()
    if not raw:
        return ''

    # Keep it URL-friendly and consistent.
    raw = raw.replace(' ', '')
    raw = re.sub(r'[^a-zA-Z0-9_.]', '', raw)
    raw = raw.lower()
    if not raw:
        return ''
    if raw[0].isdigit():
        raw = 'u' + raw
    return raw[:15]


def _normalize_email(raw: str) -> str:
    return (raw or '').strip().lower()


def _is_valid_username(raw: str) -> bool:
    raw = (raw or '').strip()
    # 3–15 chars; only URL-friendly symbols; disallow leading digit/dot to keep URLs predictable.
    return re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.]{2,14}", raw) is not None


def _find_user_by_username(username: str) -> User | None:
    u = (username or '').strip()
    if not u:
        return None
    try:
        return User.query.filter(db.func.lower(User.username) == u.lower()).first()
    except Exception:
        return None


def _find_user_by_email(email: str) -> User | None:
    e = _normalize_email(email)
    if not e:
        return None
    try:
        return User.query.filter(db.func.lower(User.email) == e.lower()).first()
    except Exception:
        return None


def _username_exists(username: str) -> bool:
    u = (username or '').strip()
    if not u:
        return False
    try:
        return User.query.filter(db.func.lower(User.username) == u.lower()).first() is not None
    except Exception:
        return False


def _generate_unique_username(raw: str) -> str:
    base = (_username_seed(raw) or '').lower()
    if not base or not _is_valid_username(base):
        base = 'user'
    if not _username_exists(base):
        return base
    for i in range(2, 1000):
        cand = _fit_with_suffix(base, str(i), 15)
        if _is_valid_username(cand) and not _username_exists(cand):
            return cand
    return _fit_with_suffix('user', str(secrets.randbelow(1000000)).zfill(6), 15)


def _login_user(user: User) -> None:
    session['user_id'] = user.id
    session['username'] = user.username


def _fit_with_suffix(base: str, suffix: str, max_len: int = 15) -> str:
    if len(suffix) >= max_len:
        return suffix[:max_len]
    base = (base or '')
    base = base[: max_len - len(suffix)]
    return base + suffix


def _username_candidates_from_raw(raw: str, max_candidates: int = 40) -> list[str]:
    raw = (raw or '').strip()
    tokens = re.findall(r'[a-zA-Z0-9]+', raw.lower())

    seeds: list[str] = []
    direct = _username_seed(raw)
    if direct:
        seeds.append(direct)

    if tokens:
        first = tokens[0]
        last = tokens[-1]
        if first:
            seeds.append(_username_seed(first))
        if last and last != first:
            seeds.append(_username_seed(last))
        if first and last and first != last:
            seeds.append(_username_seed(first + last))
            seeds.append(_username_seed(first[0] + last))
            seeds.append(_username_seed(first + '.' + last))

    # De-dupe, keep order.
    seen = set()
    seeds = [s for s in seeds if s and not (s in seen or seen.add(s))]
    if not seeds:
        return []

    years = [str(_utcnow().year), '2026', '24', '01']
    suffixes: list[str] = ['']
    suffixes += [str(i) for i in range(1, 21)]
    suffixes += ['_' + str(i) for i in range(1, 21)]
    suffixes += years

    candidates: list[str] = []
    for seed in seeds:
        for suf in suffixes:
            cand = _fit_with_suffix(seed, suf, 15)
            if len(cand) < 3:
                continue
            if cand not in candidates:
                candidates.append(cand)
            if len(candidates) >= max_candidates:
                return candidates

    # Add a few randomized variants at the end.
    for _ in range(10):
        seed = random.choice(seeds)
        n = random.randint(10, 999)
        cand = _fit_with_suffix(seed, str(n), 15)
        if len(cand) >= 3 and cand not in candidates:
            candidates.append(cand)
        if len(candidates) >= max_candidates:
            break
    return candidates


def _available_username_suggestions(raw: str, limit: int = 8) -> list[str]:
    candidates = _username_candidates_from_raw(raw)
    if not candidates:
        return []

    # Case-insensitive uniqueness check.
    lowers = [c.lower() for c in candidates]
    existing = {
        (u.username or '').lower()
        for u in User.query.filter(db.func.lower(User.username).in_(lowers)).all()
    }
    out: list[str] = []
    for c in candidates:
        if c.lower() in existing:
            continue
        out.append(c)
        if len(out) >= limit:
            break
    return out

# ------------------ ROUTES ------------------

@app.route('/')
def front():
    return render_template('front.html')


@app.route('/healthz')
def healthz():
    db_ok = True
    try:
        # Best-effort DB ping; keep it fast and non-invasive.
        db.session.execute(text('SELECT 1'))
    except Exception:
        db_ok = False

    status = 200 if db_ok else 503
    return jsonify({'ok': True, 'db_ok': db_ok, 'env': ENV_NAME}), status


@app.route('/privacy')
def privacy_policy():
    return render_template('privacy.html')


@app.route('/terms')
def terms_and_conditions():
    return render_template('terms.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password')
        email = _normalize_email(request.form.get('email') or '')
        cpwd = request.form.get('confirm_password')
        accept_terms = request.form.get('accept_terms')

        if not username or not password or not email:
            return render_template(
                'register.html',
                error="Please fill all fields.",
                prefill_username=username or '',
                prefill_email=email or '',
            ), 400

        if not _is_valid_username(username):
            return render_template(
                'register.html',
                error="Username must be 3–15 characters and contain only letters, numbers, underscore, dot.",
                suggestions=_available_username_suggestions(username),
                prefill_username=username or '',
                prefill_email=email or '',
            ), 400

        if accept_terms != 'on':
            return render_template(
                'register.html',
                error="Please accept the Terms & Conditions and Privacy Policy to continue.",
                prefill_username=username or '',
                prefill_email=email or '',
            ), 400
        # Check duplicates
        if User.query.filter(db.func.lower(User.username) == username.lower()).first():
            return render_template(
                'register.html',
                error="Username already exists.",
                suggestions=_available_username_suggestions(username),
                prefill_username=username or '',
                prefill_email=email or '',
            ), 400

        if User.query.filter(db.func.lower(User.email) == email.lower()).first():
            return render_template(
                'register.html',
                error="Email already exists.",
                prefill_username=username or '',
                prefill_email=email or '',
            ), 400

        hashed_password = generate_password_hash(password)
        
        if password != cpwd:
            return render_template(
                'register.html',
                error="Passwords do not match.",
                prefill_username=username or '',
                prefill_email=email or '',
            ), 400
        new_user = User(
            username=username,
            password=hashed_password,
            email=email,
            email_verified=False,
            display_name=username,
        )

        db.session.add(new_user)
        db.session.commit()

        # Mark this browser session as having just created an account.
        # We'll trigger the one-time onboarding tour after the first successful sign-in.
        session['new_account'] = '1'

        if _email_verification_required() and not getattr(new_user, 'email_verified', False):
            sent, _dev_code = _send_verification_otp(new_user)
            if PRODUCTION and not sent:
                return render_template(
                    'register.html',
                    error="Could not send OTP. Please try again later.",
                    prefill_username=username or '',
                    prefill_email=email or '',
                ), 503
            return redirect(url_for('email_not_verified', username=new_user.username))

        return redirect(url_for('login', registered='1'))
    return render_template('register.html')


@app.route('/api/username/suggestions', methods=['POST'])
def api_username_suggestions():
    payload = request.get_json(silent=True) or {}
    raw = (payload.get('username') or payload.get('name') or '').strip()
    seed = _username_seed(raw)

    if not raw:
        return jsonify({'ok': True, 'seed': '', 'available': False, 'suggestions': []})

    if len(seed) < 3:
        return jsonify({'ok': True, 'seed': seed, 'available': False, 'suggestions': _available_username_suggestions(raw)})

    exists = User.query.filter(db.func.lower(User.username) == seed.lower()).first() is not None
    return jsonify({
        'ok': True,
        'seed': seed,
        'available': not exists,
        'suggestions': [] if not exists else _available_username_suggestions(raw),
    })
@app.route('/login.html')
def login_page():
    return redirect(url_for('login'))

@app.route('/register.html')
def register_page():
    return render_template('register.html')

@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = (request.form.get('username') or '').strip()
        password = request.form.get('password')

        user = _find_user_by_username(identifier)
        if not user and '@' in identifier:
            user = _find_user_by_email(identifier)
        
        if user and check_password_hash(user.password, password):
            if _email_verification_required() and not getattr(user, 'email_verified', False):
                return redirect(url_for('email_not_verified', username=user.username))
            _login_user(user)

            # Trigger onboarding only for newly created accounts, and only once.
            if session.pop('new_account', None) == '1' and not getattr(user, 'onboarding_seen', False):
                session['show_onboarding'] = '1'

            return redirect(url_for('chats'))
        else:
            return render_template('login.html', error="Invalid username or password."), 401
            
    ok = None
    if request.args.get('registered') == '1':
        ok = "Account created. Please sign in."
    return render_template('login.html', ok=ok)


@app.route('/email/not-verified')
def email_not_verified():
    username = (request.args.get('username') or '').strip()
    dev_code = ''
    if not username:
        return render_template('email_not_verified.html', username='', dev_code='')

    user = _find_user_by_username(username)
    if not user:
        return render_template('email_not_verified.html', username=username, dev_code='')

    if getattr(user, 'email_verified', False):
        return redirect(url_for('chats'))

    # Ensure there is a currently valid OTP for this user.
    # We only auto-send if there isn't an active (unexpired, unconsumed) OTP.
    now = _utcnow()
    active = (
        EmailVerifyOTP.query
        .filter(
            EmailVerifyOTP.user_id == int(user.id),
            db.func.lower(EmailVerifyOTP.email) == _normalize_email(user.email).lower(),
            EmailVerifyOTP.consumed_at.is_(None),
            EmailVerifyOTP.expires_at >= now,
        )
        .order_by(EmailVerifyOTP.created_at.desc())
        .first()
    )
    if not active:
        sent, dc = _send_verification_otp(user)
        if PRODUCTION and not sent:
            # Render page; user can try Resend.
            dc = None
        dev_code = dc or ''

    return render_template('email_not_verified.html', username=username, dev_code=dev_code)


@app.route('/email/resend', methods=['POST'])
def resend_verification_email():
    payload = request.get_json(silent=True) or {}
    identifier = (payload.get('username') or payload.get('email') or '').strip()
    if not identifier:
        return jsonify({'error': 'missing_username_or_email'}), 400

    user = _find_user_by_username(identifier)
    if not user and '@' in identifier:
        user = _find_user_by_email(identifier)
    if not user:
        return jsonify({'error': 'user_not_found'}), 404
    if getattr(user, 'email_verified', False):
        return jsonify({'ok': True, 'status': 'already_verified'})

    sent, dev_code = _send_verification_otp(user)
    if PRODUCTION and not sent:
        return jsonify({'error': 'email_send_failed'}), 503
    out = {'ok': True, 'sent': bool(sent)}
    if dev_code:
        out['dev_code'] = dev_code
    return jsonify(out)


@app.route('/api/email/verify/otp/resend', methods=['POST'])
def api_email_verify_otp_resend():
    return resend_verification_email()


@app.route('/api/email/verify/otp/confirm', methods=['POST'])
def api_email_verify_otp_confirm():
    payload = request.get_json(silent=True) or {}
    username = (payload.get('username') or '').strip()
    code = (payload.get('code') or '').strip()
    if not username or not code:
        return jsonify({'error': 'missing_fields'}), 400
    if not re.fullmatch(r"\d{6}", code):
        return jsonify({'error': 'invalid_code'}), 400

    user = _find_user_by_username(username)
    if not user:
        return jsonify({'error': 'user_not_found'}), 404
    if getattr(user, 'email_verified', False):
        _login_user(user)
        # If this browser session just created an account, trigger the one-time tour.
        if session.pop('new_account', None) == '1' and not getattr(user, 'onboarding_seen', False):
            session['show_onboarding'] = '1'
        return jsonify({'ok': True, 'status': 'already_verified'})

    now = _utcnow()
    otps = (
        EmailVerifyOTP.query
        .filter(
            EmailVerifyOTP.user_id == int(user.id),
            db.func.lower(EmailVerifyOTP.email) == _normalize_email(user.email).lower(),
            EmailVerifyOTP.consumed_at.is_(None),
            EmailVerifyOTP.expires_at >= now,
        )
        .order_by(EmailVerifyOTP.created_at.desc())
        .limit(10)
        .all()
    )
    if not otps:
        return jsonify({'error': 'code_expired_or_missing'}), 400

    matched: EmailVerifyOTP | None = None
    for otp in otps:
        if int(getattr(otp, 'attempts', 0) or 0) >= 5:
            continue
        if check_password_hash(otp.code_hash, code):
            matched = otp
            break

    if not matched:
        # Increment attempts on the newest OTP to slow brute force.
        newest = otps[0]
        newest.attempts = int(getattr(newest, 'attempts', 0) or 0) + 1
        db.session.commit()
        if int(getattr(newest, 'attempts', 0) or 0) >= 5:
            return jsonify({'error': 'too_many_attempts'}), 429
        return jsonify({'error': 'invalid_code'}), 401

    matched.consumed_at = now
    user.email_verified = True
    db.session.commit()

    _login_user(user)
    # If this browser session just created an account, trigger the one-time tour.
    if session.pop('new_account', None) == '1' and not getattr(user, 'onboarding_seen', False):
        session['show_onboarding'] = '1'
    return jsonify({'ok': True})


# ------------------ AUTH: Google OAuth ------------------

GOOGLE_OIDC_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"


def _google_client_id() -> str:
    return (os.environ.get('GOOGLE_CLIENT_ID') or '').strip()


def _google_client_secret() -> str:
    return (os.environ.get('GOOGLE_CLIENT_SECRET') or '').strip()


_google_cache: dict[str, object] = {}


def _google_oidc_config() -> dict:
    cached = _google_cache.get('oidc')
    if isinstance(cached, dict) and cached.get('issuer'):
        return cached
    r = requests.get(GOOGLE_OIDC_DISCOVERY_URL, timeout=10)
    r.raise_for_status()
    cfg = r.json()
    _google_cache['oidc'] = cfg
    return cfg


def _google_jwks() -> dict:
    cached = _google_cache.get('jwks')
    if isinstance(cached, dict) and cached.get('keys'):
        return cached
    cfg = _google_oidc_config()
    jwks_uri = cfg.get('jwks_uri')
    if not jwks_uri:
        raise RuntimeError('Google OIDC jwks_uri missing')
    r = requests.get(jwks_uri, timeout=10)
    r.raise_for_status()
    jwks = r.json()
    _google_cache['jwks'] = jwks
    return jwks


def _google_redirect_uri() -> str:
    # Allow override for platforms where external URL differs.
    override = (os.environ.get('GOOGLE_REDIRECT_URI') or '').strip()
    if override:
        return override
    return url_for('auth_google_callback', _external=True)


def _google_decode_id_token(id_token: str) -> dict:
    client_id = _google_client_id()
    if not client_id:
        raise RuntimeError('GOOGLE_CLIENT_ID not configured')
    jwks = _google_jwks()
    key_set = JsonWebKey.import_key_set(jwks)
    claims_options = {
        'iss': {'values': ['https://accounts.google.com', 'accounts.google.com']},
        'aud': {'essential': True, 'value': client_id},
    }
    claims = jwt.decode(id_token, key_set, claims_options=claims_options)
    claims.validate()
    return dict(claims)


@app.route('/auth/google/start')
def auth_google_start():
    if not _google_client_id() or not _google_client_secret():
        return render_template('login.html', error='Google sign-in is not configured.'), 503

    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    session['google_oauth_state'] = state
    session['google_oauth_nonce'] = nonce

    cfg = _google_oidc_config()
    auth_endpoint = cfg.get('authorization_endpoint')
    if not auth_endpoint:
        return render_template('login.html', error='Google sign-in is temporarily unavailable.'), 503

    params = {
        'client_id': _google_client_id(),
        'redirect_uri': _google_redirect_uri(),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'nonce': nonce,
        'prompt': 'select_account',
    }
    from urllib.parse import urlencode

    return redirect(auth_endpoint + '?' + urlencode(params))


@app.route('/auth/google/callback')
def auth_google_callback():
    err = (request.args.get('error') or '').strip()
    if err:
        return render_template('login.html', error=f'Google sign-in failed: {err}'), 401

    state = (request.args.get('state') or '').strip()
    code = (request.args.get('code') or '').strip()
    if not state or not code:
        return render_template('login.html', error='Google sign-in failed.'), 400

    expected = session.get('google_oauth_state')
    if not expected or expected != state:
        return render_template('login.html', error='Google sign-in state mismatch.'), 400

    cfg = _google_oidc_config()
    token_endpoint = cfg.get('token_endpoint')
    if not token_endpoint:
        return render_template('login.html', error='Google sign-in is temporarily unavailable.'), 503

    data = {
        'code': code,
        'client_id': _google_client_id(),
        'client_secret': _google_client_secret(),
        'redirect_uri': _google_redirect_uri(),
        'grant_type': 'authorization_code',
    }
    r = requests.post(token_endpoint, data=data, timeout=15)
    if r.status_code >= 400:
        return render_template('login.html', error='Google sign-in token exchange failed.'), 401

    token = r.json()
    id_token = (token.get('id_token') or '').strip()
    if not id_token:
        return render_template('login.html', error='Google sign-in returned no ID token.'), 401

    try:
        claims = _google_decode_id_token(id_token)
    except Exception:
        return render_template('login.html', error='Google sign-in token verification failed.'), 401

    sub = (claims.get('sub') or '').strip()
    email = _normalize_email(claims.get('email') or '')
    name = (claims.get('name') or '').strip()
    if not sub or not email:
        return render_template('login.html', error='Google sign-in did not provide an email.'), 401

    acct = OAuthAccount.query.filter_by(provider='google', provider_user_id=sub).first()
    user = None
    if acct:
        user = _db_get(User, int(acct.user_id))
    if not user:
        user = _find_user_by_email(email)

    if not user:
        # Create a new local account for this Google identity.
        local_part = email.split('@', 1)[0]
        username = _generate_unique_username(local_part)
        random_password = secrets.token_urlsafe(32)
        user = User(
            username=username,
            password=generate_password_hash(random_password),
            email=email,
            email_verified=True,
            display_name=(name or username),
        )
        db.session.add(user)
        db.session.commit()

    # Ensure verified for Google accounts.
    if not getattr(user, 'email_verified', False):
        user.email_verified = True
        db.session.commit()

    if not acct:
        db.session.add(OAuthAccount(provider='google', provider_user_id=sub, user_id=user.id, email=email))
        db.session.commit()

    _login_user(user)
    return redirect(url_for('chats'))


# ------------------ AUTH: Email OTP ------------------


def _client_ip() -> str:
    # With ProxyFix enabled, request.remote_addr should already be correct.
    return (request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or request.remote_addr or '')[:64]


def _otp_seconds() -> int:
    try:
        return int(os.environ.get('OTP_TTL_SECONDS') or '600')
    except Exception:
        return 600


def _otp_rate_limited(email: str, ip: str) -> bool:
    now = _utcnow()
    try:
        recent_email = EmailOTP.query.filter(
            db.func.lower(EmailOTP.email) == email.lower(),
            EmailOTP.created_at >= (now - timedelta(minutes=10)),
        ).count()
        recent_ip = 0
        if ip:
            recent_ip = EmailOTP.query.filter(
                EmailOTP.ip == ip,
                EmailOTP.created_at >= (now - timedelta(minutes=10)),
            ).count()
        return recent_email >= 3 or recent_ip >= 10
    except Exception:
        return True


@app.route('/api/auth/otp/request', methods=['POST'])
def api_auth_otp_request():
    payload = request.get_json(silent=True) or {}
    email = _normalize_email(payload.get('email') or '')
    if not email or '@' not in email:
        return jsonify({'error': 'invalid_email'}), 400

    ip = _client_ip()
    if _otp_rate_limited(email, ip):
        return jsonify({'error': 'rate_limited'}), 429

    code = str(secrets.randbelow(1000000)).zfill(6)
    otp = EmailOTP(
        email=email,
        code_hash=generate_password_hash(code),
        expires_at=_utcnow() + timedelta(seconds=_otp_seconds()),
        ip=ip,
        user_agent=(request.headers.get('User-Agent') or '')[:200],
    )
    db.session.add(otp)
    db.session.commit()

    subject = 'LinkUp: your login code'
    body = (
        "Your LinkUp login code is:\n\n"
        f"{code}\n\n"
        f"This code expires in {_otp_seconds() // 60} minutes. If you didn't request it, you can ignore this email.\n"
    )

    sent = _send_email(email, subject, body)
    if PRODUCTION and not sent:
        return jsonify({'error': 'email_send_failed'}), 503

    resp = {'ok': True, 'sent': bool(sent)}
    if (not PRODUCTION) and (not sent) and (not _smtp_configured()):
        resp['dev_code'] = code
    return jsonify(resp)


@app.route('/api/auth/otp/verify', methods=['POST'])
def api_auth_otp_verify():
    payload = request.get_json(silent=True) or {}
    email = _normalize_email(payload.get('email') or '')
    code = (payload.get('code') or '').strip()
    if not email or not code:
        return jsonify({'error': 'missing_fields'}), 400
    if not re.fullmatch(r"\d{6}", code):
        return jsonify({'error': 'invalid_code'}), 400

    now = _utcnow()
    otp = (
        EmailOTP.query
        .filter(
            db.func.lower(EmailOTP.email) == email.lower(),
            EmailOTP.consumed_at.is_(None),
            EmailOTP.expires_at >= now,
        )
        .order_by(EmailOTP.created_at.desc())
        .first()
    )
    if not otp:
        return jsonify({'error': 'code_expired_or_missing'}), 400

    if int(getattr(otp, 'attempts', 0) or 0) >= 5:
        return jsonify({'error': 'too_many_attempts'}), 429

    if not check_password_hash(otp.code_hash, code):
        otp.attempts = int(getattr(otp, 'attempts', 0) or 0) + 1
        db.session.commit()
        return jsonify({'error': 'invalid_code'}), 401

    otp.consumed_at = now
    db.session.commit()

    user = _find_user_by_email(email)
    if not user:
        local_part = email.split('@', 1)[0]
        username = _generate_unique_username(local_part)
        random_password = secrets.token_urlsafe(32)
        user = User(
            username=username,
            password=generate_password_hash(random_password),
            email=email,
            email_verified=True,
            display_name=username,
        )
        db.session.add(user)
        db.session.commit()
    else:
        if not getattr(user, 'email_verified', False):
            user.email_verified = True
            db.session.commit()

    _login_user(user)
    return jsonify({'ok': True})


@app.route('/verify-email/<string:token>')
def verify_email(token: str):
    if not EMAIL_VERIFY_LINK_ENABLED:
        # Legacy flow disabled; OTP verification is the primary path.
        return render_template(
            'email_verified.html',
            ok=False,
            error='This verification link flow is disabled. Please verify using the OTP sent to your email.',
        ), 410

    token = (token or '').strip()
    if not token:
        return render_template('email_verified.html', ok=False, error='Invalid link.'), 400

    try:
        data = _load_email_verify_token(token)
    except SignatureExpired:
        return render_template('email_verified.html', ok=False, error='Verification link expired. Please request a new one.'), 400
    except BadSignature:
        return render_template('email_verified.html', ok=False, error='Invalid verification link.'), 400

    uid = data.get('uid')
    email = (data.get('email') or '').lower().strip()
    if not uid or not email:
        return render_template('email_verified.html', ok=False, error='Invalid verification payload.'), 400

    user = _db_get(User, int(uid))
    if not user:
        return render_template('email_verified.html', ok=False, error='User not found.'), 404
    if (user.email or '').lower().strip() != email:
        return render_template('email_verified.html', ok=False, error='Email mismatch.'), 400

    if not getattr(user, 'email_verified', False):
        user.email_verified = True
        db.session.commit()

    return render_template('email_verified.html', ok=True)


@app.route('/chats')
def chats():
    me = _get_me()
    if not me:
        return redirect(url_for('login'))

    show_onboarding = (session.pop('show_onboarding', None) == '1') and (not getattr(me, 'onboarding_seen', False))

    nova = _get_or_create_nova_user() if NOVA_ENABLED else None

    accepted = (
        ContactRequest.query
        .filter(
            ContactRequest.status == 'accepted',
            db.or_(ContactRequest.requester_id == me.id, ContactRequest.addressee_id == me.id),
        )
        .all()
    )

    contact_ids = []
    for rel in accepted:
        other_id = rel.addressee_id if rel.requester_id == me.id else rel.requester_id
        if other_id != me.id:
            contact_ids.append(other_id)

    users = []
    if contact_ids:
        users = (
            User.query
            .filter(User.id.in_(contact_ids))
            .order_by(User.username.asc())
            .all()
        )

    # NOVA is accessed via the floating widget (not shown in sidebar).

    # Groups sidebar
    group_ids = [gm.group_id for gm in GroupMember.query.filter_by(user_id=me.id).all()]
    groups = []
    if group_ids:
        groups = Group.query.filter(Group.id.in_(group_ids)).order_by(Group.created_at.desc()).all()

    group_id_raw = (request.args.get('g') or request.args.get('group') or '').strip()
    active_group = None
    if group_id_raw:
        try:
            gid = int(group_id_raw)
            if _is_group_member(me.id, gid):
                active_group = _db_get(Group, gid)
        except Exception:
            active_group = None

    to_username = request.args.get('to', '').strip()
    active_user = None

    if active_group:
        active_user = None
    elif to_username:
        # Allow a built-in "Saved Messages" (chat to self).
        if to_username.lower() == (me.username or '').lower():
            active_user = me
        else:
            # Allow a built-in NOVA bot chat.
            if _is_nova_username(to_username) and nova:
                active_user = nova
            else:
                active_user = _find_user_by_username(to_username)
                if active_user and not _is_accepted_contact(me.id, active_user.id):
                    active_user = None
    elif users:
        # Prefer a real contact (not NOVA) as the default open chat.
        active_user = next((u for u in users if not _is_nova_username(u.username)), None)
        # If the only available chat is NOVA, keep the screen idle until user selects it.
        if not active_user and to_username == '':
            active_user = None
    elif nova:
        active_user = None

    is_self_chat = bool(active_user and active_user.id == me.id)
    is_group_chat = bool(active_group is not None)
    active_kind = 'group' if is_group_chat else ('user' if active_user else '')
    has_active_chat = bool(active_user or active_group)

    is_nova_chat = bool(active_user and _is_nova_username(getattr(active_user, 'username', '')))
    nova_icon_url = url_for('static', filename='nova_logo.svg')

    group_avatar_url = _group_avatar_url(active_group) if is_group_chat else ''
    active_avatar_url = (
        group_avatar_url
        if is_group_chat
        else (_avatar_url(me) if is_self_chat else (nova_icon_url if is_nova_chat else (_avatar_url(active_user) if active_user else '')))
    )

    return render_template(
        'chats.html',
        me=me,
        users=users,
        groups=groups,
        active_user=active_user,
        active_group=active_group,
        active_kind=active_kind,
        has_active_chat=has_active_chat,
        show_onboarding=show_onboarding,
        me_avatar_url=_avatar_url(me),
        active_avatar_url=active_avatar_url,
        is_self_chat=is_self_chat,
        is_group_chat=is_group_chat,
    )


@app.route('/api/me/onboarding_seen', methods=['POST'])
def api_me_onboarding_seen():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    try:
        if not getattr(me, 'onboarding_seen', False):
            me.onboarding_seen = True
            db.session.commit()
        return jsonify({'ok': True, 'onboarding_seen': True})
    except Exception:
        return jsonify({'ok': False}), 500


@app.route('/api/presence/ping', methods=['POST'])
def api_presence_ping():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    updated = _touch_last_seen(me)
    return jsonify({
        'ok': True,
        'updated': bool(updated),
        'server_time': _utcnow().isoformat() + 'Z',
        'online_window_seconds': _presence_window_seconds(),
    })


@app.route('/api/groups/<int:group_id>/messages', methods=['GET'])
def api_group_messages_get(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    if not _is_group_member(me.id, int(group_id)):
        return jsonify({'error': 'not_a_member'}), 403

    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404

    since_id_raw = (request.args.get('since_id') or '').strip()
    since_id = None
    if since_id_raw.isdigit():
        since_id = int(since_id_raw)

    msg_query = GroupMessage.query.filter(GroupMessage.group_id == int(group_id))
    if since_id:
        msg_query = msg_query.filter(GroupMessage.id > since_id)

    msgs = (
        msg_query
        .order_by(GroupMessage.created_at.asc(), GroupMessage.id.asc())
        .limit(300)
        .all()
    )

    sender_ids = sorted({m.sender_id for m in msgs}) if msgs else []
    senders = {}
    if sender_ids:
        for u in User.query.filter(User.id.in_(sender_ids)).all():
            senders[u.id] = u.username

    # Reply preview (within group)
    reply_ids = sorted({int(m.reply_to_id) for m in msgs if getattr(m, 'reply_to_id', None)})
    replied: dict[int, GroupMessage] = {}
    if reply_ids:
        for rm in GroupMessage.query.filter(GroupMessage.id.in_(reply_ids)).all():
            replied[int(rm.id)] = rm

    latest_visible_message_id = int(msgs[-1].id) if msgs else None
    _mark_group_chat_read(me.id, int(group_id), latest_visible_message_id)

    return jsonify([
        {
            'id': m.id,
            'sender_username': senders.get(m.sender_id, 'unknown'),
            'recipient_username': g.name,
            **_transport_text_fields(
                'content',
                '' if getattr(m, 'deleted_for_all', False) else _safe_decrypt_message_content(m.content),
            ),
            'attachment_url': '',
            'attachment_name': '',
            'attachment_mime': '',
            'attachment_size': 0,
            'reply': (
                {
                    'id': int(m.reply_to_id),
                    'sender_username': senders.get(replied[int(m.reply_to_id)].sender_id, 'unknown') if int(m.reply_to_id) in replied else 'unknown',
                    **_transport_text_fields(
                        'text',
                        (
                            '' if (int(m.reply_to_id) not in replied or getattr(replied[int(m.reply_to_id)], 'deleted_for_all', False))
                            else _safe_decrypt_message_content(replied[int(m.reply_to_id)].content)
                        )[:120],
                    ),
                    'has_attachment': False,
                    'deleted_for_all': bool(int(m.reply_to_id) in replied and getattr(replied[int(m.reply_to_id)], 'deleted_for_all', False)),
                }
                if getattr(m, 'reply_to_id', None)
                else None
            ),
            'edited_at': (m.edited_at.isoformat() + 'Z') if getattr(m, 'edited_at', None) else '',
            'deleted_for_all': bool(getattr(m, 'deleted_for_all', False)),
            'starred': False,
            'pinned': False,
            'can_edit': bool(m.sender_id == me.id),
            'can_delete_for_everyone': False,
            'created_at': m.created_at.isoformat() + 'Z',
        }
        for m in msgs
    ])


@app.route('/api/groups/<int:group_id>/messages', methods=['POST'])
def api_group_messages_post(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    if not _is_group_member(me.id, int(group_id)):
        return jsonify({'error': 'not_a_member'}), 403

    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404

    payload = request.get_json(silent=True) or {}
    try:
        content = (_payload_text_field(payload, 'content') or '').strip()
    except Exception:
        return jsonify({'error': 'invalid_transport_payload'}), 400
    reply_to_id = payload.get('reply_to_id')
    if not content:
        return jsonify({'error': 'empty_message'}), 400
    if len(content) > 2000:
        return jsonify({'error': 'message_too_long'}), 400

    reply_to = None
    try:
        if reply_to_id is not None and str(reply_to_id).strip() != '':
            rid = int(reply_to_id)
            reply_to = _db_get(GroupMessage, rid)
            if not reply_to or int(reply_to.group_id) != int(group_id):
                reply_to = None
    except Exception:
        reply_to = None

    stored_content = encrypt_text(content)
    msg = GroupMessage(group_id=int(group_id), sender_id=me.id, content=stored_content)
    if reply_to:
        msg.reply_to_id = int(reply_to.id)
    db.session.add(msg)
    db.session.commit()
    return jsonify({'ok': True, 'id': msg.id})


@app.route('/api/groups/<int:group_id>', methods=['GET'])
def api_group_get(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404
    if not _is_group_member(me.id, int(group_id)):
        return jsonify({'error': 'not_a_member'}), 403
    return jsonify({
        'ok': True,
        'id': g.id,
        'name': g.name,
        'owner_id': g.owner_id,
        'is_admin': False,
        'image_url': _group_avatar_url(g),
        'image_locked': bool(getattr(g, 'image_locked', False)),
        'created_at': g.created_at.isoformat() + 'Z',
    })


@app.route('/api/groups/<int:group_id>/image', methods=['POST'])
def api_group_image_upload(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404
    if not _is_group_member(me.id, int(group_id)):
        return jsonify({'error': 'not_a_member'}), 403
    if getattr(g, 'image_locked', False):
        return jsonify({'error': 'image_locked'}), 403

    f = request.files.get('image')
    if not f or not f.filename:
        return jsonify({'error': 'missing_file'}), 400

    ext = _allowed_group_image_ext(f.filename)
    if not ext:
        return jsonify({'error': 'unsupported_file_type'}), 400

    size = _file_size_bytes(f)
    if size < 0:
        return jsonify({'error': 'invalid_file'}), 400
    if size > 2 * 1024 * 1024:
        return jsonify({'error': 'file_too_large'}), 413

    ctype = (f.mimetype or '').lower()
    if ctype and not ctype.startswith('image/'):
        return jsonify({'error': 'invalid_content_type'}), 400

    _group_avatars_dir().mkdir(parents=True, exist_ok=True)

    if getattr(g, 'image_filename', None):
        _delete_group_image_file(g)

    stamp = int(_utcnow().timestamp())
    filename = f"group_{g.id}_{stamp}_{random.randint(1000,9999)}{ext}"
    path = _group_avatars_dir() / filename
    f.save(path)

    g.image_filename = filename
    g.image_locked = False
    db.session.commit()

    return jsonify({'ok': True, 'image_url': _group_avatar_url(g), 'image_locked': False})


def _existing_group_image_poll(group_id: int, kind: str) -> GroupPoll | None:
    return GroupPoll.query.filter_by(group_id=int(group_id), kind=kind, status='open').first()


@app.route('/api/groups/<int:group_id>/image/lock', methods=['POST'])
def api_group_image_lock_poll(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404
    if not _is_group_member(me.id, int(group_id)):
        return jsonify({'error': 'not_a_member'}), 403
    if not getattr(g, 'image_filename', None):
        return jsonify({'error': 'missing_image'}), 400
    if getattr(g, 'image_locked', False):
        return jsonify({'error': 'already_locked'}), 409

    existing = _existing_group_image_poll(group_id, 'image_lock')
    if existing:
        return jsonify({'ok': True, 'status': 'poll_open', 'poll_id': existing.id})

    poll = GroupPoll(group_id=int(g.id), kind='image_lock', created_by_id=int(me.id), target_username='__group_image__', status='open')
    db.session.add(poll)
    db.session.commit()

    try:
        db.session.add(GroupPollVote(poll_id=int(poll.id), user_id=int(me.id), vote='yes'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    result = _poll_finalize_if_needed(poll)
    return jsonify({'ok': True, 'status': 'poll_created', 'poll_id': poll.id, 'result': result})


@app.route('/api/groups/<int:group_id>/image/remove', methods=['POST'])
def api_group_image_remove_poll(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404
    if not _is_group_member(me.id, int(group_id)):
        return jsonify({'error': 'not_a_member'}), 403
    if not getattr(g, 'image_filename', None):
        return jsonify({'error': 'missing_image'}), 400

    existing = _existing_group_image_poll(group_id, 'image_remove')
    if existing:
        return jsonify({'ok': True, 'status': 'poll_open', 'poll_id': existing.id})

    poll = GroupPoll(group_id=int(g.id), kind='image_remove', created_by_id=int(me.id), target_username='__group_image__', status='open')
    db.session.add(poll)
    db.session.commit()

    try:
        db.session.add(GroupPollVote(poll_id=int(poll.id), user_id=int(me.id), vote='yes'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    result = _poll_finalize_if_needed(poll)
    return jsonify({'ok': True, 'status': 'poll_created', 'poll_id': poll.id, 'result': result})


@app.route('/api/groups/<int:group_id>/members', methods=['GET'])
def api_group_members(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404
    if not _is_group_member(me.id, int(group_id)):
        return jsonify({'error': 'not_a_member'}), 403

    members = GroupMember.query.filter_by(group_id=int(group_id)).order_by(GroupMember.created_at.asc()).all()
    user_ids = [m.user_id for m in members]
    users = {u.id: u for u in (User.query.filter(User.id.in_(user_ids)).all() if user_ids else [])}

    return jsonify([
        {
            'user_id': m.user_id,
            'username': (users.get(m.user_id).username if users.get(m.user_id) else 'unknown'),
            'role': 'member',
            'is_owner': False,
            'created_at': m.created_at.isoformat() + 'Z',
        }
        for m in members
    ])


@app.route('/api/groups/<int:group_id>/rename', methods=['POST'])
def api_group_rename(group_id: int):
    return jsonify({'error': 'rename_disabled'}), 403


@app.route('/api/groups/<int:group_id>/leave', methods=['POST'])
def api_group_leave(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404

    gm = GroupMember.query.filter_by(group_id=int(group_id), user_id=me.id).first()
    if not gm:
        return jsonify({'error': 'not_a_member'}), 403

    db.session.delete(gm)
    db.session.commit()
    _delete_group_if_empty(int(group_id))
    return jsonify({'ok': True})


@app.route('/api/groups/<int:group_id>/delete', methods=['POST'])
def api_group_delete(group_id: int):
    return jsonify({'error': 'delete_disabled'}), 403


@app.route('/api/groups/<int:group_id>/polls', methods=['GET'])
def api_group_polls_list(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404
    if not _is_group_member(me.id, int(group_id)):
        return jsonify({'error': 'not_a_member'}), 403

    polls = (
        GroupPoll.query
        .filter_by(group_id=int(group_id))
        .order_by(GroupPoll.created_at.desc())
        .limit(30)
        .all()
    )

    # Preload related users.
    uids = set()
    for p in polls:
        if p.created_by_id:
            uids.add(int(p.created_by_id))
        if p.target_user_id:
            uids.add(int(p.target_user_id))
    users = {u.id: u for u in (User.query.filter(User.id.in_(list(uids))).all() if uids else [])}

    # Votes info
    my_votes = {v.poll_id: v.vote for v in GroupPollVote.query.filter(GroupPollVote.user_id == me.id, GroupPollVote.poll_id.in_([p.id for p in polls] if polls else [])).all()}

    out = []
    for p in polls:
        ex = _poll_excluded_subject_user_id(p)
        yes, no = _poll_counts(p.id, exclude_user_id=ex)
        total = len(_poll_eligible_member_ids(p))
        out.append({
            'id': p.id,
            'group_id': p.group_id,
            'kind': p.kind,
            'status': p.status,
            'created_at': p.created_at.isoformat() + 'Z',
            'decided_at': p.decided_at.isoformat() + 'Z' if p.decided_at else '',
            'created_by_username': (users.get(p.created_by_id).username if users.get(p.created_by_id) else 'unknown'),
            'target_username': (
                users.get(p.target_user_id).username if (p.target_user_id and users.get(p.target_user_id))
                else (p.target_username or '')
            ),
            'yes': yes,
            'no': no,
            'total': total,
            'my_vote': my_votes.get(p.id, ''),
        })

    return jsonify(out)


@app.route('/api/groups/polls/<int:poll_id>/vote', methods=['POST'])
def api_group_poll_vote(poll_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    poll = _db_get(GroupPoll, int(poll_id))
    if not poll:
        return jsonify({'error': 'poll_not_found'}), 404
    if not _is_group_member(me.id, int(poll.group_id)):
        return jsonify({'error': 'not_a_member'}), 403

    # Subject of a removal poll cannot vote on it.
    try:
        if (poll.kind or '') == 'remove':
            subject_id = _poll_excluded_subject_user_id(poll)
            if subject_id is not None and int(subject_id) == int(me.id):
                return jsonify({'error': 'poll_subject_cannot_vote'}), 403
    except Exception:
        pass
    if (poll.status or '') != 'open':
        return jsonify({'ok': True, 'status': poll.status})

    payload = request.get_json(silent=True) or {}
    vote = (payload.get('vote') or '').strip().lower()
    if vote not in ('yes', 'no'):
        return jsonify({'error': 'invalid_vote'}), 400

    existing = GroupPollVote.query.filter_by(poll_id=int(poll.id), user_id=int(me.id)).first()
    if existing:
        existing.vote = vote
        db.session.commit()
    else:
        try:
            db.session.add(GroupPollVote(poll_id=int(poll.id), user_id=int(me.id), vote=vote))
            db.session.commit()
        except Exception:
            # If two rapid requests race, one insert may hit the unique constraint.
            # Recover by re-reading and updating instead of failing the vote.
            db.session.rollback()
            existing = GroupPollVote.query.filter_by(poll_id=int(poll.id), user_id=int(me.id)).first()
            if existing:
                existing.vote = vote
                try:
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                    return jsonify({'error': 'vote_failed'}), 400
            else:
                return jsonify({'error': 'vote_failed'}), 400

    result = _poll_finalize_if_needed(poll)
    return jsonify({'ok': True, 'poll_id': poll.id, 'result': result})


@app.route('/api/groups/<int:group_id>/members/remove', methods=['POST'])
def api_group_member_remove(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404
    if not _is_group_member(me.id, g.id):
        return jsonify({'error': 'not_a_member'}), 403

    payload = request.get_json(silent=True) or {}
    username = (payload.get('username') or '').strip()
    if not username:
        return jsonify({'error': 'missing_username'}), 400

    other = User.query.filter(db.func.lower(User.username) == username.lower()).first()
    if not other:
        return jsonify({'error': 'user_not_found'}), 404

    if int(other.id) == int(me.id):
        return jsonify({'error': 'use_exit_to_leave'}), 400

    gm = GroupMember.query.filter_by(group_id=int(group_id), user_id=int(other.id)).first()
    if not gm:
        return jsonify({'error': 'not_a_member'}), 400

    existing_poll = GroupPoll.query.filter_by(group_id=int(g.id), kind='remove', status='open').filter(
        db.or_(GroupPoll.target_user_id == other.id, db.func.lower(GroupPoll.target_username) == other.username.lower())
    ).first()
    if existing_poll:
        return jsonify({'ok': True, 'status': 'poll_open', 'poll_id': existing_poll.id})

    poll = GroupPoll(group_id=int(g.id), kind='remove', created_by_id=int(me.id), target_user_id=int(other.id), target_username=other.username, status='open')
    db.session.add(poll)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        existing_poll = GroupPoll.query.filter_by(group_id=int(g.id), kind='remove', status='open').filter(
            db.or_(GroupPoll.target_user_id == other.id, db.func.lower(GroupPoll.target_username) == other.username.lower())
        ).first()
        if existing_poll:
            return jsonify({'ok': True, 'status': 'poll_open', 'poll_id': existing_poll.id})
        return jsonify({'error': 'poll_create_failed'}), 400

    # proposer auto-votes yes
    try:
        db.session.add(GroupPollVote(poll_id=int(poll.id), user_id=int(me.id), vote='yes'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    result = _poll_finalize_if_needed(poll)
    return jsonify({'ok': True, 'status': 'poll_created', 'poll_id': poll.id, 'poll': result})


@app.route('/api/contacts/inbox', methods=['GET'])
def api_contacts_inbox():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    reqs = (
        ContactRequest.query
        .filter(ContactRequest.addressee_id == me.id, ContactRequest.status == 'pending')
        .order_by(ContactRequest.created_at.desc())
        .all()
    )

    requester_ids = [r.requester_id for r in reqs]
    requesters = {}
    if requester_ids:
        for u in User.query.filter(User.id.in_(requester_ids)).all():
            requesters[u.id] = u.username

    return jsonify([
        {
            'from_username': requesters.get(r.requester_id, 'unknown'),
            'created_at': r.created_at.isoformat() + 'Z',
        }
        for r in reqs
    ])


@app.route('/api/contacts/sent', methods=['GET'])
def api_contacts_sent():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    reqs = (
        ContactRequest.query
        .filter(ContactRequest.requester_id == me.id, ContactRequest.status == 'pending')
        .order_by(ContactRequest.created_at.desc())
        .all()
    )

    addressee_ids = [r.addressee_id for r in reqs]
    addressees = {}
    if addressee_ids:
        for u in User.query.filter(User.id.in_(addressee_ids)).all():
            addressees[u.id] = u.username

    return jsonify([
        {
            'to_username': addressees.get(r.addressee_id, 'unknown'),
            'created_at': r.created_at.isoformat() + 'Z',
        }
        for r in reqs
    ])


@app.route('/api/contacts/request', methods=['POST'])
def api_contacts_request():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    to_username = (payload.get('username') or '').strip().lstrip('@').strip()
    if not to_username:
        return jsonify({'error': 'missing_username'}), 400

    other = User.query.filter(db.func.lower(User.username) == to_username.lower()).first()
    if not other:
        return jsonify({'error': 'user_not_found'}), 404
    if other.id == me.id:
        return jsonify({'error': 'cannot_add_self'}), 400

    existing = _contact_request_between(me.id, other.id)
    if existing:
        if existing.status == 'accepted':
            return jsonify({'ok': True, 'status': 'accepted'})

        # If there's a pending request, either it's incoming (they requested you)
        # or it's already sent by you.
        if existing.status == 'pending':
            if existing.addressee_id == me.id:
                return jsonify({'error': 'incoming_request_pending'}), 409
            return jsonify({'ok': True, 'status': 'pending'})

        # Previously declined (or any non-pending state): allow re-request.
        # Re-open it as a new pending request from `me` to `other`.
        existing.requester_id = me.id
        existing.addressee_id = other.id
        existing.status = 'pending'
        existing.created_at = _utcnow()
        db.session.commit()
        return jsonify({'ok': True, 'status': 'pending'})

    rel = ContactRequest(requester_id=me.id, addressee_id=other.id, status='pending')
    db.session.add(rel)
    db.session.commit()
    return jsonify({'ok': True, 'status': 'pending'})


@app.route('/api/account/me', methods=['GET'])
def api_account_me():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401
    return jsonify({
        'username': me.username,
        'email': me.email,
        'display_name': me.display_name or '',
        'about': me.about or '',
        'avatar_color': me.avatar_color or '',
        'avatar_url': _avatar_url(me),
    })


@app.route('/api/users/<string:username>/public', methods=['GET'])
def api_user_public(username: str):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    username = (username or '').strip()
    if not username:
        return jsonify({'error': 'missing_username'}), 400

    other = _find_user_by_username(username)
    if not other:
        return jsonify({'error': 'user_not_found'}), 404

    if other.id != me.id and not _is_accepted_contact(me.id, other.id):
        return jsonify({'error': 'not_a_contact'}), 403

    presence = _presence_payload_for(other)
    return jsonify({
        'username': other.username,
        'display_name': other.display_name or '',
        'about': other.about or '',
        'avatar_url': _avatar_url(other),
        'is_online': presence.get('is_online', False),
        'last_seen_at': presence.get('last_seen_at', ''),
    })


@app.route('/api/account/profile', methods=['GET', 'POST'])
def api_account_profile():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    if request.method == 'GET':
        return jsonify({
            'username': me.username,
            'display_name': me.display_name or '',
            'about': me.about or '',
            'avatar_color': me.avatar_color or '',
            'avatar_url': _avatar_url(me),
        })

    payload = request.get_json(silent=True) or {}
    display_name = (payload.get('display_name') or '').strip()
    about = (payload.get('about') or '').strip()

    if display_name and len(display_name) > 40:
        return jsonify({'error': 'display_name_too_long'}), 400
    if about and len(about) > 140:
        return jsonify({'error': 'about_too_long'}), 400

    me.display_name = display_name or me.username
    me.about = about
    db.session.commit()

    return jsonify({'ok': True, 'display_name': me.display_name, 'about': me.about or ''})


@app.route('/api/account/avatar', methods=['POST'])
def api_account_avatar_upload():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    f = request.files.get('avatar')
    if not f or not f.filename:
        return jsonify({'error': 'missing_file'}), 400

    ext = _allowed_avatar_ext(f.filename)
    if not ext:
        return jsonify({'error': 'unsupported_file_type'}), 400

    size = _file_size_bytes(f)
    if size < 0:
        return jsonify({'error': 'invalid_file'}), 400
    if size > 2 * 1024 * 1024:
        return jsonify({'error': 'file_too_large'}), 413

    # Very light content-type check (clients may omit it); extension is primary.
    ctype = (f.mimetype or '').lower()
    if ctype and not ctype.startswith('image/'):
        return jsonify({'error': 'invalid_content_type'}), 400

    _avatars_dir().mkdir(parents=True, exist_ok=True)

    # Remove old avatar file if any.
    if me.avatar_filename:
        try:
            (_avatars_dir() / me.avatar_filename).unlink(missing_ok=True)
        except Exception:
            pass

    stamp = int(_utcnow().timestamp())
    base = secure_filename(me.username) or f"user{me.id}"
    filename = f"{base}_{me.id}_{stamp}{ext}"
    path = _avatars_dir() / filename
    f.save(path)

    me.avatar_filename = filename
    db.session.commit()

    return jsonify({'ok': True, 'avatar_url': _avatar_url(me) + f"?v={stamp}"})


@app.route('/api/account/avatar/delete', methods=['POST'])
def api_account_avatar_delete():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    if me.avatar_filename:
        try:
            (_avatars_dir() / me.avatar_filename).unlink(missing_ok=True)
        except Exception:
            pass
        me.avatar_filename = None
        db.session.commit()

    return jsonify({'ok': True})


@app.route('/api/account/email', methods=['POST'])
def api_account_update_email():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    email = (payload.get('email') or '').strip().lower()
    current_password = payload.get('current_password') or ''
    if not email or '@' not in email:
        return jsonify({'error': 'invalid_email'}), 400
    if not current_password:
        return jsonify({'error': 'missing_password'}), 400
    if not check_password_hash(me.password, current_password):
        return jsonify({'error': 'invalid_current_password'}), 401

    if email == (me.email or '').lower().strip():
        return jsonify({'ok': True, 'email': me.email, 'verification': 'unchanged'})

    existing = User.query.filter(db.func.lower(User.email) == email.lower(), User.id != me.id).first()
    if existing:
        return jsonify({'error': 'email_exists'}), 409

    me.email = email
    me.email_verified = False
    db.session.commit()

    if _email_verification_required():
        sent, dev_code = _send_verification_otp(me)
        if PRODUCTION and not sent:
            return jsonify({'error': 'email_send_failed'}), 503
        out = {'ok': True, 'email': me.email, 'verification': 'required', 'sent': bool(sent)}
        if dev_code:
            out['dev_code'] = dev_code
        return jsonify(out)

    return jsonify({'ok': True, 'email': me.email, 'verification': 'optional'})


@app.route('/api/account/password', methods=['POST'])
def api_account_change_password():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    current_password = payload.get('current_password') or ''
    new_password = payload.get('new_password') or ''
    confirm_password = payload.get('confirm_password') or ''

    if not current_password or not new_password or not confirm_password:
        return jsonify({'error': 'missing_fields'}), 400
    if new_password != confirm_password:
        return jsonify({'error': 'passwords_do_not_match'}), 400
    if len(new_password) < 5:
        return jsonify({'error': 'password_too_short'}), 400
    if not check_password_hash(me.password, current_password):
        return jsonify({'error': 'invalid_current_password'}), 401

    me.password = generate_password_hash(new_password)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/contacts/list', methods=['GET', 'POST'])
def api_contacts_list():
    """Get list of all accepted contacts for current user."""
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    # Get all accepted contact requests
    accepted_reqs = (
        ContactRequest.query
        .filter(
            db.or_(
                db.and_(ContactRequest.requester_id == me.id, ContactRequest.status == 'accepted'),
                db.and_(ContactRequest.addressee_id == me.id, ContactRequest.status == 'accepted')
            )
        )
        .all()
    )

    # Collect other user IDs
    other_ids = []
    for req in accepted_reqs:
        if req.requester_id == me.id:
            other_ids.append(req.addressee_id)
        else:
            other_ids.append(req.requester_id)

    # Get user details
    contacts = []
    if other_ids:
        users = User.query.filter(User.id.in_(other_ids)).all()
        for u in users:
            contacts.append({
                'username': u.username,
                'display_name': u.display_name or u.username,
                'about': u.about or '',
                'avatar_url': _avatar_url(u),
            })

    return jsonify({'ok': True, 'contacts': contacts})


@app.route('/api/account/username', methods=['POST'])
def api_account_username_verify():
    """Verify password and validate new username before changing."""
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    new_username = (payload.get('new_username') or '').strip()
    current_password = payload.get('current_password') or ''

    if not current_password:
        return jsonify({'error': 'missing_password'}), 400
    if not check_password_hash(me.password, current_password):
        return jsonify({'error': 'invalid_password'}), 401

    if not new_username:
        return jsonify({'error': 'missing_username'}), 400
    if len(new_username) < 3 or len(new_username) > 15:
        return jsonify({'error': 'invalid_username_length'}), 400
    if not re.match(r'^[a-zA-Z0-9_]+$', new_username):
        return jsonify({'error': 'invalid_username_format'}), 400
    if new_username.lower() == me.username.lower():
        return jsonify({'error': 'same_username'}), 400

    # Check if username exists (exclude self)
    existing = User.query.filter(
        db.func.lower(User.username) == new_username.lower(),
        User.id != me.id,
    ).first()
    if existing:
        return jsonify({'error': 'username_taken'}), 409

    return jsonify({'ok': True})


@app.route('/api/account/username/finalize', methods=['POST'])
def api_account_username_finalize():
    """Finalize username change.

    - Updates username
    - Deletes existing contacts (ContactRequest rows)
    - Leaves all groups
    - Sends new contact requests to selected contacts
    - Starts invite polls in selected groups to re-add the user
    """
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    new_username = (payload.get('new_username') or '').strip()
    current_password = payload.get('current_password') or ''
    selected_contacts = payload.get('selected_contacts') or []
    selected_groups = payload.get('selected_groups') or []

    # Normalize group IDs early.
    selected_group_ids: list[int] = []
    for gid in selected_groups:
        try:
            selected_group_ids.append(int(gid))
        except Exception:
            continue
    # Deduplicate, keep order.
    seen = set()
    selected_group_ids = [g for g in selected_group_ids if not (g in seen or seen.add(g))]

    # Snapshot groups we are currently in (used for leaving + poll targeting).
    my_group_ids = [gm.group_id for gm in GroupMember.query.filter_by(user_id=me.id).all()]

    # For each group, pick a poll creator who will remain in the group after we leave.
    poll_creator_by_group: dict[int, int] = {}
    if my_group_ids:
        groups = {g.id: g for g in Group.query.filter(Group.id.in_(my_group_ids)).all()}
        for gid in my_group_ids:
            g = groups.get(int(gid))
            creator_id = None
            if g and g.owner_id and int(g.owner_id) != int(me.id):
                owner_member = GroupMember.query.filter_by(group_id=int(gid), user_id=int(g.owner_id)).first()
                if owner_member:
                    creator_id = int(g.owner_id)
            if not creator_id:
                other_member = (
                    GroupMember.query
                    .filter(GroupMember.group_id == int(gid), GroupMember.user_id != int(me.id))
                    .first()
                )
                if other_member:
                    creator_id = int(other_member.user_id)
            if creator_id:
                poll_creator_by_group[int(gid)] = int(creator_id)

    # Re-verify password
    if not current_password:
        return jsonify({'error': 'missing_password'}), 400
    if not check_password_hash(me.password, current_password):
        return jsonify({'error': 'invalid_password'}), 401

    # Re-validate username
    if not new_username:
        return jsonify({'error': 'missing_username'}), 400
    if len(new_username) < 3 or len(new_username) > 15:
        return jsonify({'error': 'invalid_username_length'}), 400
    if not re.match(r'^[a-zA-Z0-9_]+$', new_username):
        return jsonify({'error': 'invalid_username_format'}), 400

    if new_username.lower() == me.username.lower():
        return jsonify({'error': 'same_username'}), 400

    # Check if username exists
    existing = User.query.filter(
        db.func.lower(User.username) == new_username.lower(),
        User.id != me.id,
    ).first()
    if existing:
        return jsonify({'error': 'username_taken'}), 409

    # Delete all existing contact relationships
    ContactRequest.query.filter(
        db.or_(ContactRequest.requester_id == me.id, ContactRequest.addressee_id == me.id)
    ).delete(synchronize_session=False)

    # Update username
    old_username = me.username
    me.username = new_username
    if me.display_name == old_username:
        me.display_name = new_username
    db.session.commit()

    # Keep session mirrors in sync (some pages use this)
    try:
        session['username'] = me.username
    except Exception:
        pass

    # Send new contact requests to selected users
    sent_count = 0
    if selected_contacts:
        for contact_username in selected_contacts:
            contact_username = (contact_username or '').strip()
            if not contact_username:
                continue
            other = User.query.filter(db.func.lower(User.username) == contact_username.lower()).first()
            if other and other.id != me.id:
                try:
                    rel = ContactRequest(requester_id=me.id, addressee_id=other.id, status='pending')
                    db.session.add(rel)
                    db.session.commit()
                    sent_count += 1
                except Exception:
                    db.session.rollback()

    # Leave all groups after username change.
    left_groups = 0
    if my_group_ids:
        try:
            GroupMember.query.filter(
                GroupMember.user_id == int(me.id),
                GroupMember.group_id.in_(my_group_ids),
            ).delete(synchronize_session=False)
            db.session.commit()
            left_groups = len(my_group_ids)
        except Exception:
            db.session.rollback()

        # Clean up groups that became empty.
        for gid in my_group_ids:
            _delete_group_if_empty(int(gid))

    # Start invite polls in selected groups so the user can re-join.
    polls_started = 0
    if selected_group_ids:
        for gid in selected_group_ids:
            if gid not in my_group_ids:
                continue
            creator_id = poll_creator_by_group.get(int(gid))
            if not creator_id:
                # No remaining members => group will be deleted; nothing to poll.
                continue

            # Avoid duplicate open polls for the same target.
            existing_open = (
                GroupPoll.query
                .filter_by(group_id=int(gid), kind='invite', status='open', target_user_id=int(me.id))
                .first()
            )
            if existing_open:
                continue

            # Ensure the group still exists and has members.
            g = _db_get(Group, int(gid))
            if not g:
                continue
            if GroupMember.query.filter_by(group_id=int(gid)).count() <= 0:
                continue

            try:
                poll = GroupPoll(
                    group_id=int(gid),
                    kind='invite',
                    created_by_id=int(creator_id),
                    target_user_id=int(me.id),
                    target_username=str(me.username),
                    status='open',
                )
                db.session.add(poll)
                db.session.commit()
                polls_started += 1
            except Exception:
                db.session.rollback()

    return jsonify({
        'ok': True,
        'new_username': me.username,
        'requests_sent': sent_count,
        'left_groups': left_groups,
        'group_polls_started': polls_started,
    })


@app.route('/api/account/delete', methods=['POST'])
def api_account_delete():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    current_password = payload.get('current_password') or ''
    if not current_password or not check_password_hash(me.password, current_password):
        return jsonify({'error': 'invalid_current_password'}), 401

    # Cleanup data that references this user.
    try:
        uploads = (
            Message.query
            .filter(db.or_(Message.sender_id == me.id, Message.recipient_id == me.id))
            .filter(Message.attachment_filename.isnot(None))
            .with_entities(Message.attachment_filename)
            .all()
        )
        for (fn,) in uploads:
            if not fn:
                continue
            try:
                (_uploads_dir() / fn).unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass

    Message.query.filter(db.or_(Message.sender_id == me.id, Message.recipient_id == me.id)).delete(synchronize_session=False)
    MessageDeletion.query.filter(MessageDeletion.user_id == me.id).delete(synchronize_session=False)
    MessageStar.query.filter(MessageStar.user_id == me.id).delete(synchronize_session=False)
    MessagePin.query.filter(MessagePin.user_id == me.id).delete(synchronize_session=False)
    ContactRequest.query.filter(
        db.or_(ContactRequest.requester_id == me.id, ContactRequest.addressee_id == me.id)
    ).delete(synchronize_session=False)

    SupportTicket.query.filter(SupportTicket.user_id == me.id).delete(synchronize_session=False)

    if me.avatar_filename:
        try:
            (_avatars_dir() / me.avatar_filename).unlink(missing_ok=True)
        except Exception:
            pass

    db.session.delete(me)
    db.session.commit()

    session.clear()
    return jsonify({'ok': True, 'redirect': url_for('front')})


@app.route('/support', methods=['GET', 'POST'])
def support():
    me = _get_me()
    if not me:
        return redirect(url_for('login'))

    ok = None
    error = None

    if request.method == 'POST':
        category = (request.form.get('category') or 'general').strip().lower()
        subject = (request.form.get('subject') or '').strip()
        message = (request.form.get('message') or '').strip()

        if not subject or not message:
            error = 'Please fill subject and message.'
        elif len(subject) > 80:
            error = 'Subject is too long.'
        elif len(message) > 1200:
            error = 'Message is too long.'
        else:
            t = SupportTicket(
                user_id=me.id,
                category=category[:20],
                subject=subject,
                message=message,
            )
            db.session.add(t)
            db.session.commit()
            ok = 'Ticket submitted. We’ll get back to you.'

    tickets = (
        SupportTicket.query
        .filter(SupportTicket.user_id == me.id)
        .order_by(SupportTicket.created_at.desc(), SupportTicket.id.desc())
        .limit(15)
        .all()
    )

    return render_template('support.html', me=me, tickets=tickets, ok=ok, error=error)


@app.route('/api/contacts/accept', methods=['POST'])
def api_contacts_accept():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    from_username = (payload.get('username') or '').strip().lstrip('@').strip()
    if not from_username:
        return jsonify({'error': 'missing_username'}), 400

    other = User.query.filter(db.func.lower(User.username) == from_username.lower()).first()
    if not other:
        return jsonify({'error': 'user_not_found'}), 404
    if other.id == me.id:
        return jsonify({'error': 'cannot_accept_self'}), 400

    rel = (
        ContactRequest.query
        .filter(
            ContactRequest.requester_id == other.id,
            ContactRequest.addressee_id == me.id,
            ContactRequest.status == 'pending',
        )
        .first()
    )

    if not rel:
        return jsonify({'error': 'no_pending_request'}), 404

    rel.status = 'accepted'
    db.session.commit()
    return jsonify({'ok': True, 'status': 'accepted'})


@app.route('/api/contacts/reject', methods=['POST'])
def api_contacts_reject():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    from_username = (payload.get('username') or '').strip().lstrip('@').strip()
    if not from_username:
        return jsonify({'error': 'missing_username'}), 400

    other = User.query.filter(db.func.lower(User.username) == from_username.lower()).first()
    if not other:
        return jsonify({'error': 'user_not_found'}), 404
    if other.id == me.id:
        return jsonify({'error': 'cannot_reject_self'}), 400

    rel = (
        ContactRequest.query
        .filter(
            ContactRequest.requester_id == other.id,
            ContactRequest.addressee_id == me.id,
            ContactRequest.status == 'pending',
        )
        .first()
    )

    if not rel:
        return jsonify({'error': 'no_pending_request'}), 404

    rel.status = 'declined'
    db.session.commit()
    return jsonify({'ok': True, 'status': 'declined'})


@app.route('/api/contacts/withdraw', methods=['POST'])
def api_contacts_withdraw():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    to_username = (payload.get('username') or '').strip().lstrip('@').strip()
    if not to_username:
        return jsonify({'error': 'missing_username'}), 400

    other = User.query.filter(db.func.lower(User.username) == to_username.lower()).first()
    if not other:
        return jsonify({'error': 'user_not_found'}), 404

    rel = (
        ContactRequest.query
        .filter(
            ContactRequest.requester_id == me.id,
            ContactRequest.addressee_id == other.id,
            ContactRequest.status == 'pending',
        )
        .first()
    )

    if not rel:
        return jsonify({'error': 'no_pending_sent_request'}), 404

    db.session.delete(rel)
    db.session.commit()
    return jsonify({'ok': True})


# ------------------ GROUPS (Invites / Requests) ------------------


def _is_group_admin(user_id: int, group_id: int) -> bool:
    # Groups intentionally have no admins/owners for permissions.
    return False


@app.route('/api/groups', methods=['GET', 'POST'])
def api_groups_list():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    group_ids = [gm.group_id for gm in GroupMember.query.filter_by(user_id=me.id).all()]
    groups = []
    if group_ids:
        groups = Group.query.filter(Group.id.in_(group_ids)).order_by(Group.created_at.desc()).all()

    return jsonify([
        {
            'id': g.id,
            'name': g.name,
            'owner_id': g.owner_id,
            'created_at': g.created_at.isoformat() + 'Z',
        }
        for g in groups
    ])


@app.route('/api/groups/invites/inbox', methods=['GET'])
def api_group_invites_inbox():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    invs = (
        GroupInvite.query
        .filter(GroupInvite.invitee_id == me.id, GroupInvite.status == 'pending')
        .order_by(GroupInvite.created_at.desc())
        .all()
    )

    group_ids = [i.group_id for i in invs]
    inviter_ids = [i.inviter_id for i in invs]

    groups = {g.id: g for g in (Group.query.filter(Group.id.in_(group_ids)).all() if group_ids else [])}
    inviters = {u.id: u for u in (User.query.filter(User.id.in_(inviter_ids)).all() if inviter_ids else [])}

    return jsonify([
        {
            'invite_id': i.id,
            'group_id': i.group_id,
            'group_name': (groups.get(i.group_id).name if groups.get(i.group_id) else 'Group'),
            'from_username': (inviters.get(i.inviter_id).username if inviters.get(i.inviter_id) else 'unknown'),
            'created_at': i.created_at.isoformat() + 'Z',
        }
        for i in invs
    ])


@app.route('/api/groups/invites/sent', methods=['GET'])
def api_group_invites_sent():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    invs = (
        GroupInvite.query
        .filter(GroupInvite.inviter_id == me.id, GroupInvite.status == 'pending')
        .order_by(GroupInvite.created_at.desc())
        .all()
    )

    group_ids = [i.group_id for i in invs]
    invitee_ids = [i.invitee_id for i in invs]
    groups = {g.id: g for g in (Group.query.filter(Group.id.in_(group_ids)).all() if group_ids else [])}
    invitees = {u.id: u for u in (User.query.filter(User.id.in_(invitee_ids)).all() if invitee_ids else [])}

    return jsonify([
        {
            'invite_id': i.id,
            'group_id': i.group_id,
            'group_name': (groups.get(i.group_id).name if groups.get(i.group_id) else 'Group'),
            'to_username': (invitees.get(i.invitee_id).username if invitees.get(i.invitee_id) else 'unknown'),
            'created_at': i.created_at.isoformat() + 'Z',
        }
        for i in invs
    ])


@app.route('/api/groups/create', methods=['POST'])
def api_groups_create():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or payload.get('group_name') or '').strip()
    members = payload.get('members') or payload.get('usernames') or []
    if not isinstance(members, list):
        members = []

    if not name:
        return jsonify({'error': 'missing_group_name'}), 400
    if len(name) > 40:
        return jsonify({'error': 'group_name_too_long'}), 400

    g = Group(name=name, owner_id=me.id)
    db.session.add(g)
    db.session.commit()

    creation_token = _make_group_creation_token(g.id, me.id)

    # Creator is a normal member.
    db.session.add(GroupMember(group_id=g.id, user_id=me.id, role='member'))
    db.session.commit()

    # Send invites.
    invited: list[str] = []
    not_found: list[str] = []
    skipped: list[str] = []

    # normalize + unique
    usernames = []
    for raw in members:
        if raw is None:
            continue
        u = str(raw).strip()
        if not u:
            continue
        if u.lower() not in [x.lower() for x in usernames]:
            usernames.append(u)

    for uname in usernames:
        if uname.lower() == (me.username or '').lower():
            skipped.append(uname)
            continue
        other = User.query.filter(db.func.lower(User.username) == uname.lower()).first()
        if not other:
            not_found.append(uname)
            continue
        # already member?
        if GroupMember.query.filter_by(group_id=g.id, user_id=other.id).first():
            skipped.append(uname)
            continue
        try:
            inv = GroupInvite(group_id=g.id, inviter_id=me.id, invitee_id=other.id, status='pending')
            db.session.add(inv)
            db.session.commit()
            invited.append(other.username)
        except Exception:
            db.session.rollback()
            skipped.append(uname)

    return jsonify({'ok': True, 'group_id': g.id, 'name': g.name, 'creation_token': creation_token, 'invited': invited, 'not_found': not_found, 'skipped': skipped})


@app.route('/api/groups/<int:group_id>/invite', methods=['POST'])
def api_groups_invite(group_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    g = _db_get(Group, int(group_id))
    if not g:
        return jsonify({'error': 'group_not_found'}), 404
    if not _is_group_member(me.id, g.id):
        return jsonify({'error': 'not_a_member'}), 403

    payload = request.get_json(silent=True) or {}
    to_username = (payload.get('username') or '').strip()
    creation_token = (payload.get('creation_token') or '').strip()
    if not to_username:
        return jsonify({'error': 'missing_username'}), 400

    other = User.query.filter(db.func.lower(User.username) == to_username.lower()).first()
    if not other:
        return jsonify({'error': 'user_not_found'}), 404
    if other.id == me.id:
        return jsonify({'error': 'cannot_invite_self'}), 400

    if GroupMember.query.filter_by(group_id=g.id, user_id=other.id).first():
        return jsonify({'ok': True, 'status': 'already_member'})

    # Allow bypassing polls only during initial group creation flow (short-lived token, owner only).
    if creation_token:
        try:
            data = _load_group_creation_token(creation_token, max_age_seconds=10 * 60)
            if int(data.get('gid') or 0) == int(g.id) and int(data.get('uid') or 0) == int(me.id) and int(g.owner_id) == int(me.id):
                existing = GroupInvite.query.filter_by(group_id=g.id, invitee_id=other.id).first()
                if existing:
                    if existing.status == 'pending':
                        return jsonify({'ok': True, 'status': 'pending'})
                    existing.status = 'pending'
                    existing.inviter_id = me.id
                    db.session.commit()
                    return jsonify({'ok': True, 'status': 'pending'})

                inv = GroupInvite(group_id=g.id, inviter_id=me.id, invitee_id=other.id, status='pending')
                db.session.add(inv)
                db.session.commit()
                return jsonify({'ok': True, 'status': 'pending'})
        except (BadSignature, SignatureExpired, Exception):
            # fall through to poll
            pass

    # Poll-based invite: create a poll and let members vote.
    existing_poll = GroupPoll.query.filter_by(group_id=int(g.id), kind='invite', status='open').filter(
        db.or_(GroupPoll.target_user_id == other.id, db.func.lower(GroupPoll.target_username) == to_username.lower())
    ).first()
    if existing_poll:
        return jsonify({'ok': True, 'status': 'poll_open', 'poll_id': existing_poll.id})

    poll = GroupPoll(group_id=int(g.id), kind='invite', created_by_id=int(me.id), target_user_id=int(other.id), target_username=other.username, status='open')
    db.session.add(poll)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        existing_poll = GroupPoll.query.filter_by(group_id=int(g.id), kind='invite', status='open').filter(
            db.or_(GroupPoll.target_user_id == other.id, db.func.lower(GroupPoll.target_username) == to_username.lower())
        ).first()
        if existing_poll:
            return jsonify({'ok': True, 'status': 'poll_open', 'poll_id': existing_poll.id})
        return jsonify({'error': 'poll_create_failed'}), 400

    # proposer auto-votes yes
    try:
        db.session.add(GroupPollVote(poll_id=int(poll.id), user_id=int(me.id), vote='yes'))
        db.session.commit()
    except Exception:
        db.session.rollback()

    result = _poll_finalize_if_needed(poll)
    return jsonify({'ok': True, 'status': 'poll_created', 'poll_id': poll.id, 'poll': result})


@app.route('/api/groups/invites/accept', methods=['POST'])
def api_group_invites_accept():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    invite_id = payload.get('invite_id')
    if invite_id is None or str(invite_id).strip() == '':
        return jsonify({'error': 'missing_invite_id'}), 400

    inv = _db_get(GroupInvite, int(invite_id))
    if not inv:
        return jsonify({'error': 'invite_not_found'}), 404
    if inv.invitee_id != me.id:
        return jsonify({'error': 'not_invited_user'}), 403
    if inv.status != 'pending':
        return jsonify({'ok': True, 'status': inv.status})

    inv.status = 'accepted'
    # add membership
    if not GroupMember.query.filter_by(group_id=inv.group_id, user_id=me.id).first():
        db.session.add(GroupMember(group_id=inv.group_id, user_id=me.id, role='member'))
    db.session.commit()
    return jsonify({'ok': True, 'status': 'accepted', 'group_id': inv.group_id})


@app.route('/api/groups/invites/withdraw', methods=['POST'])
def api_group_invites_withdraw():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    invite_id = payload.get('invite_id')
    if invite_id is None or str(invite_id).strip() == '':
        return jsonify({'error': 'missing_invite_id'}), 400

    inv = _db_get(GroupInvite, int(invite_id))
    if not inv:
        return jsonify({'error': 'invite_not_found'}), 404
    if inv.inviter_id != me.id:
        return jsonify({'error': 'not_inviter'}), 403
    if inv.status != 'pending':
        return jsonify({'error': 'not_pending'}), 400

    db.session.delete(inv)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/messages/<string:other_username>', methods=['GET'])
def api_get_messages(other_username: str):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    other_username = (other_username or '').strip()
    if _is_nova_username(other_username):
        if not NOVA_ENABLED:
            return jsonify({'error': 'user_not_found'}), 404
        _get_or_create_nova_user()
        other_username = NOVA_USERNAME
    other = _find_user_by_username(other_username)
    if not other:
        return jsonify({'error': 'user_not_found'}), 404

    is_self = other.id == me.id

    since_id_raw = (request.args.get('since_id') or '').strip()
    since_id = None
    if since_id_raw.isdigit():
        since_id = int(since_id_raw)

    if is_self:
        msg_query = Message.query.filter(Message.sender_id == me.id, Message.recipient_id == me.id)
    else:
        if not _is_nova_username(other.username) and not _is_accepted_contact(me.id, other.id):
            return jsonify({'error': 'not_a_contact'}), 403
        msg_query = Message.query.filter(
            db.or_(
                db.and_(Message.sender_id == me.id, Message.recipient_id == other.id),
                db.and_(Message.sender_id == other.id, Message.recipient_id == me.id),
            )
        )

    if since_id:
        msg_query = msg_query.filter(Message.id > since_id)

    msgs = (
        msg_query
        .order_by(Message.created_at.asc(), Message.id.asc())
        .limit(300)
        .all()
    )

    if msgs:
        ids = [m.id for m in msgs]
        deleted_ids = {
            d.message_id
            for d in MessageDeletion.query
            .filter(MessageDeletion.user_id == me.id, MessageDeletion.message_id.in_(ids))
            .all()
        }
        if deleted_ids:
            msgs = [m for m in msgs if m.id not in deleted_ids]

    ids = [m.id for m in msgs] if msgs else []
    starred_ids: set[int] = set()
    pinned_ids: set[int] = set()
    if ids:
        starred_ids = {
            s.message_id
            for s in MessageStar.query
            .filter(MessageStar.user_id == me.id, MessageStar.message_id.in_(ids))
            .all()
        }
        pinned_ids = {
            p.message_id
            for p in MessagePin.query
            .filter(MessagePin.user_id == me.id, MessagePin.message_id.in_(ids))
            .all()
        }

    reply_ids = sorted({int(m.reply_to_id) for m in msgs if getattr(m, 'reply_to_id', None)})
    replied: dict[int, Message] = {}
    if reply_ids:
        for rm in Message.query.filter(Message.id.in_(reply_ids)).all():
            replied[int(rm.id)] = rm

    latest_visible_message_id = int(msgs[-1].id) if msgs else None
    if not is_self:
        _mark_direct_chat_read(me.id, other.id, latest_visible_message_id)

    sender_map = {me.id: me.username, other.id: other.username}
    return jsonify([
        {
            'id': m.id,
            'sender_username': sender_map.get(m.sender_id, 'unknown'),
            'recipient_username': sender_map.get(m.recipient_id, 'unknown'),
            **_transport_text_fields(
                'content',
                '' if getattr(m, 'deleted_for_all', False) else _safe_decrypt_message_content(m.content),
            ),
            'attachment_url': '' if getattr(m, 'deleted_for_all', False) else _attachment_url(m),
            'attachment_name': '' if getattr(m, 'deleted_for_all', False) else (m.attachment_original or ''),
            'attachment_mime': '' if getattr(m, 'deleted_for_all', False) else (m.attachment_mime or ''),
            'attachment_size': 0 if getattr(m, 'deleted_for_all', False) else (m.attachment_size or 0),
            'reply': (
                {
                    'id': int(m.reply_to_id),
                    'sender_username': sender_map.get(replied[int(m.reply_to_id)].sender_id, 'unknown') if int(m.reply_to_id) in replied else 'unknown',
                    **_transport_text_fields(
                        'text',
                        (
                            '' if (int(m.reply_to_id) not in replied or getattr(replied[int(m.reply_to_id)], 'deleted_for_all', False))
                            else _safe_decrypt_message_content(replied[int(m.reply_to_id)].content)
                        )[:120],
                    ),
                    'has_attachment': bool(int(m.reply_to_id) in replied and getattr(replied[int(m.reply_to_id)], 'attachment_filename', None)),
                    'deleted_for_all': bool(int(m.reply_to_id) in replied and getattr(replied[int(m.reply_to_id)], 'deleted_for_all', False)),
                }
                if getattr(m, 'reply_to_id', None)
                else None
            ),
            'edited_at': (m.edited_at.isoformat() + 'Z') if getattr(m, 'edited_at', None) else '',
            'deleted_for_all': bool(getattr(m, 'deleted_for_all', False)),
            'starred': bool(m.id in starred_ids),
            'pinned': bool(m.id in pinned_ids),
            'can_edit': _can_edit_message(me, m),
            'can_delete_for_everyone': _can_delete_for_everyone(me, m),
            'created_at': m.created_at.isoformat() + 'Z',
        }
        for m in msgs
    ])


def _safe_decrypt_message_content(stored: str) -> str:
    try:
        return decrypt_text(stored)
    except CryptoError:
        return "[Unable to decrypt message]"


@app.route('/api/chats/sidebar', methods=['GET'])
def api_chats_sidebar():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    deleted_subq = (
        db.session.query(MessageDeletion.message_id)
        .filter(MessageDeletion.user_id == me.id)
        .subquery()
    )

    accepted = (
        ContactRequest.query
        .filter(
            ContactRequest.status == 'accepted',
            db.or_(ContactRequest.requester_id == me.id, ContactRequest.addressee_id == me.id),
        )
        .all()
    )

    contact_ids: list[int] = []
    for rel in accepted:
        other_id = rel.addressee_id if rel.requester_id == me.id else rel.requester_id
        if int(other_id) != int(me.id):
            contact_ids.append(int(other_id))

    users = User.query.filter(User.id.in_(contact_ids)).all() if contact_ids else []
    direct_states = {
        int(s.other_user_id): s for s in DirectChatState.query.filter_by(user_id=int(me.id)).all()
    }

    direct_items = []
    for other in users:
        last_msg = (
            Message.query
            .filter(
                db.or_(
                    db.and_(Message.sender_id == me.id, Message.recipient_id == other.id),
                    db.and_(Message.sender_id == other.id, Message.recipient_id == me.id),
                )
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .first()
        )
        state = direct_states.get(int(other.id))
        last_read_message_id = int(state.last_read_message_id or 0) if state else 0
        unread_query = Message.query.filter(
            Message.sender_id == other.id,
            Message.recipient_id == me.id,
            Message.deleted_for_all == False,
            Message.id > last_read_message_id,
        )
        if deleted_subq is not None:
            unread_query = unread_query.filter(~Message.id.in_(deleted_subq))
        unread_count = unread_query.count()

        preview = ''
        created_at = ''
        last_message_id = 0
        last_sender_username = ''
        if last_msg:
            preview = _message_preview_text(
                last_msg.content,
                attachment_name=getattr(last_msg, 'attachment_original', None),
                deleted_for_all=bool(getattr(last_msg, 'deleted_for_all', False)),
            )
            created_at = (last_msg.created_at.isoformat() + 'Z') if getattr(last_msg, 'created_at', None) else ''
            last_message_id = int(last_msg.id)
            last_sender = _db_get(User, int(last_msg.sender_id)) if getattr(last_msg, 'sender_id', None) else None
            last_sender_username = str(getattr(last_sender, 'username', '') or '')

        presence = _presence_payload_for(other)
        direct_items.append({
            'kind': 'user',
            'username': other.username,
            'user_id': int(other.id),
            'unread_count': int(unread_count),
            'last_message_id': int(last_message_id),
            'last_message_at': created_at,
            'last_sender_username': last_sender_username,
            'preview': preview,
            'is_online': presence.get('is_online', False),
            'last_seen_at': presence.get('last_seen_at', ''),
        })

    direct_items.sort(key=lambda item: (0 if int(item['unread_count']) > 0 else 1, -(int(item['last_message_id']) or 0), str(item['username']).lower()))

    group_ids = [int(gm.group_id) for gm in GroupMember.query.filter_by(user_id=me.id).all()]
    groups = Group.query.filter(Group.id.in_(group_ids)).all() if group_ids else []
    group_states = {
        int(s.group_id): s for s in GroupChatState.query.filter_by(user_id=int(me.id)).all()
    }

    group_items = []
    for group in groups:
        last_group_msg = (
            GroupMessage.query
            .filter(GroupMessage.group_id == int(group.id))
            .order_by(GroupMessage.created_at.desc(), GroupMessage.id.desc())
            .first()
        )
        state = group_states.get(int(group.id))
        last_read_message_id = int(state.last_read_message_id or 0) if state else 0
        unread_count = (
            GroupMessage.query
            .filter(
                GroupMessage.group_id == int(group.id),
                GroupMessage.sender_id != int(me.id),
                GroupMessage.deleted_for_all == False,
                GroupMessage.id > last_read_message_id,
            )
            .count()
        )

        preview = ''
        created_at = ''
        last_message_id = 0
        last_sender_username = ''
        if last_group_msg:
            preview = _message_preview_text(
                last_group_msg.content,
                deleted_for_all=bool(getattr(last_group_msg, 'deleted_for_all', False)),
            )
            created_at = (last_group_msg.created_at.isoformat() + 'Z') if getattr(last_group_msg, 'created_at', None) else ''
            last_message_id = int(last_group_msg.id)
            last_sender = _db_get(User, int(last_group_msg.sender_id)) if getattr(last_group_msg, 'sender_id', None) else None
            last_sender_username = str(getattr(last_sender, 'username', '') or '')

        group_items.append({
            'kind': 'group',
            'group_id': int(group.id),
            'group_name': group.name,
            'unread_count': int(unread_count),
            'last_message_id': int(last_message_id),
            'last_message_at': created_at,
            'last_sender_username': last_sender_username,
            'preview': preview,
        })

    group_items.sort(key=lambda item: (0 if int(item['unread_count']) > 0 else 1, -(int(item['last_message_id']) or 0), str(item['group_name']).lower()))

    return jsonify({'direct': direct_items, 'groups': group_items})


def _payload_text_field(payload, field_name: str) -> str:
    transport_value = payload.get(f"{field_name}_transport")
    if isinstance(transport_value, str) and transport_value:
        return transport_decode_text(transport_value)

    value = payload.get(field_name)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _transport_text_fields(field_name: str, text: str) -> dict:
    value = text if isinstance(text, str) else ""
    try:
        transport_value = transport_encode_text(value)
    except Exception:
        transport_value = ""
    return {
        field_name: value,
        f"{field_name}_transport": transport_value,
    }


@app.route('/api/messages/<string:other_username>', methods=['POST'])
def api_send_message(other_username: str):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    other_username = (other_username or '').strip()
    if _is_nova_username(other_username):
        if not NOVA_ENABLED:
            return jsonify({'error': 'user_not_found'}), 404
        _get_or_create_nova_user()
        other_username = NOVA_USERNAME
    other = _find_user_by_username(other_username)
    if not other:
        return jsonify({'error': 'user_not_found'}), 404

    is_self = other.id == me.id

    if not is_self and (not _is_nova_username(other.username)) and not _is_accepted_contact(me.id, other.id):
        return jsonify({'error': 'not_a_contact'}), 403

    payload = request.get_json(silent=True) or {}
    try:
        content = (_payload_text_field(payload, 'content') or '').strip()
    except Exception:
        return jsonify({'error': 'invalid_transport_payload'}), 400
    reply_to_id = payload.get('reply_to_id')
    if not content:
        return jsonify({'error': 'empty_message'}), 400
    if len(content) > 2000:
        return jsonify({'error': 'message_too_long'}), 400

    reply_to = None
    try:
        if reply_to_id is not None and str(reply_to_id).strip() != '':
            rid = int(reply_to_id)
            reply_to = _db_get(Message, rid)
            if not reply_to:
                reply_to = None
            elif me.id not in (reply_to.sender_id, reply_to.recipient_id):
                reply_to = None
            elif other.id not in (reply_to.sender_id, reply_to.recipient_id):
                reply_to = None
    except Exception:
        reply_to = None

    stored_content = encrypt_text(content)
    msg = Message(sender_id=me.id, recipient_id=other.id, content=stored_content)
    if reply_to:
        msg.reply_to_id = int(reply_to.id)
    db.session.add(msg)
    db.session.commit()

    _save_global_emojis_from_text(content)

    def _is_tour_request_text(text: str) -> bool:
        t = (text or '').strip().lower()
        if not t:
            return False
        if t in ('/tour', 'tour', '/onboarding'):
            return True
        return any(
            k in t
            for k in (
                'give me a tour',
                'start the tour',
                'show me the tour',
                'show me around',
                'app tour',
                'onboarding',
                'walk me through',
                'walkthrough',
                'overview',
                'guide me',
                'guided tour',
            )
        )

    # Auto-reply when chatting with NOVA.
    if NOVA_ENABLED and _is_nova_username(other.username):
        try:
            history = _nova_history_for_user(me, other, limit=int(os.environ.get('NOVA_DB_HISTORY', '18') or '18'))

            # Fast-path: tour requests should respond immediately and consistently.
            if _is_tour_request_text(content):
                reply_text = (
                    "Starting the guided tour now. \
You’ll see highlights on the screen — click Next to continue, Skip to exit. \
You can ask me for the tour again anytime by typing /tour."
                )
            else:
                reply_text = nova_ai.generate_reply(me_username=me.username, user_text=content, history=history) or _nova_generate_reply(content, me)

            if reply_text:
                stored_reply = encrypt_text(reply_text)
                bot_msg = Message(sender_id=other.id, recipient_id=me.id, content=stored_reply)
                db.session.add(bot_msg)
                db.session.commit()
        except Exception:
            # Never break the user's send if the bot fails.
            pass

    return jsonify({'ok': True, 'id': msg.id})


@app.route('/api/messages/<string:other_username>/attachment', methods=['POST'])
def api_send_attachment(other_username: str):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    other_username = (other_username or '').strip()
    if _is_nova_username(other_username):
        if not NOVA_ENABLED:
            return jsonify({'error': 'user_not_found'}), 404
        _get_or_create_nova_user()
        other_username = NOVA_USERNAME
    other = _find_user_by_username(other_username)
    if not other:
        return jsonify({'error': 'user_not_found'}), 404

    is_self = other.id == me.id
    if not is_self and (not _is_nova_username(other.username)) and not _is_accepted_contact(me.id, other.id):
        return jsonify({'error': 'not_a_contact'}), 403

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'missing_file'}), 400

    ext = _allowed_attachment_ext(f.filename)
    if not ext:
        return jsonify({'error': 'unsupported_file_type'}), 400

    size = _file_size_bytes(f)
    if size < 0:
        return jsonify({'error': 'invalid_file'}), 400
    if size > 10 * 1024 * 1024:
        return jsonify({'error': 'file_too_large'}), 413

    try:
        caption = (_payload_text_field(request.form, 'caption') or '').strip()
    except Exception:
        return jsonify({'error': 'invalid_transport_payload'}), 400
    reply_to_id = (request.form.get('reply_to_id') or '').strip()
    if len(caption) > 2000:
        return jsonify({'error': 'message_too_long'}), 400

    reply_to = None
    try:
        if reply_to_id:
            rid = int(reply_to_id)
            reply_to = _db_get(Message, rid)
            if not reply_to:
                reply_to = None
            elif me.id not in (reply_to.sender_id, reply_to.recipient_id):
                reply_to = None
            elif other.id not in (reply_to.sender_id, reply_to.recipient_id):
                reply_to = None
    except Exception:
        reply_to = None

    _uploads_dir().mkdir(parents=True, exist_ok=True)

    stamp = int(_utcnow().timestamp())
    base = secure_filename(me.username) or f"user{me.id}"
    filename = f"{base}_{me.id}_{stamp}_{random.randint(1000,9999)}{ext}"
    path = _uploads_dir() / filename
    f.save(path)

    stored_caption = encrypt_text(caption)
    msg = Message(
        sender_id=me.id,
        recipient_id=other.id,
        content=stored_caption,
        attachment_filename=filename,
        attachment_original=(f.filename or '')[:140],
        attachment_mime=(f.mimetype or '')[:60],
        attachment_size=size,
    )
    if reply_to:
        msg.reply_to_id = int(reply_to.id)
    db.session.add(msg)
    db.session.commit()

    _auto_save_media_from_attachment(
        me,
        filename,
        (f.filename or '')[:140],
        (f.mimetype or '')[:60],
        size,
    )

    if caption:
        _save_global_emojis_from_text(caption)

    # Auto-reply for NOVA (attachments are acknowledged; bot doesn't process files).
    if NOVA_ENABLED and _is_nova_username(other.username):
        try:
            user_caption = caption if caption else 'Attachment'
            history = _nova_history_for_user(me, other, limit=int(os.environ.get('NOVA_DB_HISTORY', '18') or '18'))
            reply_text = nova_ai.generate_reply(me_username=me.username, user_text=user_caption, history=history) or _nova_generate_reply(user_caption, me)
            if reply_text:
                stored_reply = encrypt_text(reply_text)
                bot_msg = Message(sender_id=other.id, recipient_id=me.id, content=stored_reply)
                db.session.add(bot_msg)
                db.session.commit()
        except Exception:
            pass

    return jsonify({'ok': True, 'id': msg.id, 'attachment_url': _attachment_url(msg)})


@app.route('/api/emojis/library')
def api_global_emoji_library():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    rows = GlobalEmoji.query.order_by(GlobalEmoji.created_at.desc(), GlobalEmoji.id.desc()).limit(200).all()
    items = [r.emoji for r in rows if r and r.emoji]
    return jsonify({'items': items})


@app.route('/api/media/list')
def api_media_list():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    kind = (request.args.get('kind') or '').strip().lower()
    q = UserMedia.query.filter_by(user_id=int(me.id))
    if kind in ('gif', 'sticker'):
        q = q.filter_by(kind=kind)
    rows = q.order_by(UserMedia.created_at.desc(), UserMedia.id.desc()).limit(200).all()
    return jsonify({'items': [_media_response_payload(m) for m in rows]})


@app.route('/api/media/upload', methods=['POST'])
def api_media_upload():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'missing_file'}), 400

    size = _file_size_bytes(f)
    if size < 0:
        return jsonify({'error': 'invalid_file'}), 400
    if size > 10 * 1024 * 1024:
        return jsonify({'error': 'file_too_large'}), 413

    kind = _allowed_media_kind(f.mimetype or '', f.filename)
    if kind not in ('gif', 'sticker'):
        return jsonify({'error': 'unsupported_file_type'}), 400

    _ensure_media_dir()

    stamp = int(_utcnow().timestamp())
    base = secure_filename(me.username) or f"user{me.id}"
    title = (Path(f.filename).stem or kind)[:80]

    if kind == 'gif':
        filename = f"{base}_{me.id}_{stamp}_{random.randint(1000,9999)}.gif"
        path = _media_dir() / filename
        f.save(path)
        media = _save_user_media(me, 'gif', title, filename, 'image/gif', size)
    else:
        try:
            img = Image.open(f.stream)
        except Exception:
            return jsonify({'error': 'invalid_image'}), 400
        target_size = 512
        sticker = _make_sticker(img, target_size, '')
        filename = f"{base}_{me.id}_{stamp}_{random.randint(1000,9999)}.png"
        path = _media_dir() / filename
        sticker.save(path, format='PNG')
        size = int(path.stat().st_size) if path.exists() else size
        media = _save_user_media(me, 'sticker', title, filename, 'image/png', size)

    return jsonify({'item': _media_response_payload(media)})


@app.route('/api/media/sticker', methods=['POST'])
def api_media_create_sticker():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': 'missing_file'}), 400

    size = _file_size_bytes(f)
    if size < 0:
        return jsonify({'error': 'invalid_file'}), 400
    if size > 10 * 1024 * 1024:
        return jsonify({'error': 'file_too_large'}), 413

    caption = (request.form.get('caption') or '').strip()
    try:
        target_size = int(request.form.get('size') or '384')
    except Exception:
        target_size = 384
    target_size = max(128, min(640, target_size))

    try:
        img = Image.open(f.stream)
    except Exception:
        return jsonify({'error': 'invalid_image'}), 400

    _ensure_media_dir()
    stamp = int(_utcnow().timestamp())
    base = secure_filename(me.username) or f"user{me.id}"
    title = (caption or Path(f.filename).stem or 'sticker')[:80]
    filename = f"{base}_{me.id}_{stamp}_{random.randint(1000,9999)}.png"
    path = _media_dir() / filename

    sticker = _make_sticker(img, target_size, caption)
    sticker.save(path, format='PNG')
    size = int(path.stat().st_size) if path.exists() else size
    media = _save_user_media(me, 'sticker', title, filename, 'image/png', size)
    return jsonify({'item': _media_response_payload(media)})


@app.route('/api/media/gif', methods=['POST'])
def api_media_create_gif():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    frames = request.files.getlist('frames')
    if not frames:
        return jsonify({'error': 'missing_frames'}), 400
    if len(frames) > 20:
        return jsonify({'error': 'too_many_frames'}), 400

    caption = (request.form.get('caption') or '').strip()
    try:
        delay = int(request.form.get('delay') or '120')
    except Exception:
        delay = 120
    delay = max(50, min(1000, delay))

    try:
        target = int(request.form.get('size') or '320')
    except Exception:
        target = 320
    target = max(128, min(640, target))

    images: list[Image.Image] = []
    for f in frames:
        if not f or not f.filename:
            continue
        try:
            img = Image.open(f.stream)
            img = img.convert('RGBA')
            img.thumbnail((target, target), Image.LANCZOS)
            _draw_caption(img, caption)
            images.append(img)
        except Exception:
            continue

    if not images:
        return jsonify({'error': 'invalid_frames'}), 400

    _ensure_media_dir()
    stamp = int(_utcnow().timestamp())
    base = secure_filename(me.username) or f"user{me.id}"
    filename = f"{base}_{me.id}_{stamp}_{random.randint(1000,9999)}.gif"
    path = _media_dir() / filename

    first, rest = images[0], images[1:]
    first.save(
        path,
        format='GIF',
        save_all=True,
        append_images=rest,
        duration=delay,
        loop=0,
        disposal=2,
        optimize=False,
    )
    size = int(path.stat().st_size) if path.exists() else 0
    title = (caption or 'gif')[:80]
    media = _save_user_media(me, 'gif', title, filename, 'image/gif', size)
    return jsonify({'item': _media_response_payload(media)})


@app.route('/api/messages/<string:other_username>/media/<int:media_id>', methods=['POST'])
def api_send_media(other_username: str, media_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    other_username = (other_username or '').strip()
    if _is_nova_username(other_username):
        if not NOVA_ENABLED:
            return jsonify({'error': 'user_not_found'}), 404
        _get_or_create_nova_user()
        other_username = NOVA_USERNAME
    other = _find_user_by_username(other_username)
    if not other:
        return jsonify({'error': 'user_not_found'}), 404

    is_self = other.id == me.id
    if not is_self and (not _is_nova_username(other.username)) and not _is_accepted_contact(me.id, other.id):
        return jsonify({'error': 'not_a_contact'}), 403

    media = _db_get(UserMedia, media_id)
    if not media:
        return jsonify({'error': 'not_found'}), 404
    if int(media.user_id) != int(me.id):
        return jsonify({'error': 'forbidden'}), 403

    msg = Message(
        sender_id=me.id,
        recipient_id=other.id,
        content=encrypt_text(''),
        attachment_filename=media.filename,
        attachment_original=(media.title or media.filename)[:140],
        attachment_mime=media.mime,
        attachment_size=media.size,
    )
    db.session.add(msg)
    db.session.commit()

    return jsonify({'ok': True, 'id': msg.id, 'attachment_url': _attachment_url(msg)})


@app.route('/api/gifs/search')
def api_gif_search():
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    q = (request.args.get('q') or '').strip()
    limit = request.args.get('limit') or '24'

    try:
        results = _tenor_search(q, limit=int(limit))
    except RuntimeError:
        return jsonify({'error': 'gif_search_unavailable'}), 503
    except Exception:
        return jsonify({'error': 'gif_search_failed'}), 502

    return jsonify({'results': results})


@app.route('/api/messages/<string:other_username>/gif', methods=['POST'])
def api_send_gif(other_username: str):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    other_username = (other_username or '').strip()
    if _is_nova_username(other_username):
        if not NOVA_ENABLED:
            return jsonify({'error': 'user_not_found'}), 404
        _get_or_create_nova_user()
        other_username = NOVA_USERNAME
    other = _find_user_by_username(other_username)
    if not other:
        return jsonify({'error': 'user_not_found'}), 404

    is_self = other.id == me.id
    if not is_self and (not _is_nova_username(other.username)) and not _is_accepted_contact(me.id, other.id):
        return jsonify({'error': 'not_a_contact'}), 403

    payload = request.get_json(silent=True) or {}
    url = (payload.get('url') or '').strip()
    title = (payload.get('title') or '').strip()
    reply_to_id = (payload.get('reply_to_id') or '').strip()

    if not url or not _is_allowed_gif_url(url):
        return jsonify({'error': 'invalid_gif_url'}), 400

    reply_to = None
    try:
        if reply_to_id:
            rid = int(reply_to_id)
            reply_to = _db_get(Message, rid)
            if not reply_to:
                reply_to = None
            elif me.id not in (reply_to.sender_id, reply_to.recipient_id):
                reply_to = None
            elif other.id not in (reply_to.sender_id, reply_to.recipient_id):
                reply_to = None
    except Exception:
        reply_to = None

    _uploads_dir().mkdir(parents=True, exist_ok=True)

    stamp = int(_utcnow().timestamp())
    base = secure_filename(me.username) or f"user{me.id}"
    filename = f"{base}_{me.id}_{stamp}_{random.randint(1000,9999)}.gif"
    ok, size, err = _download_gif(url, filename)
    if not ok:
        return jsonify({'error': err or 'download_failed'}), 400

    safe_title = secure_filename(title) or 'gif'
    original = f"{safe_title}.gif"[:140]

    msg = Message(
        sender_id=me.id,
        recipient_id=other.id,
        content=encrypt_text(''),
        attachment_filename=filename,
        attachment_original=original,
        attachment_mime='image/gif',
        attachment_size=size or 0,
    )
    if reply_to:
        msg.reply_to_id = int(reply_to.id)
    db.session.add(msg)
    db.session.commit()

    _auto_save_media_from_attachment(
        me,
        filename,
        original,
        'image/gif',
        size or 0,
    )

    return jsonify({'ok': True, 'id': msg.id, 'attachment_url': _attachment_url(msg)})


@app.route('/api/message/<int:message_id>/delete_for_me', methods=['POST'])
def api_message_delete_for_me(message_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    msg = _db_get(Message, message_id)
    if not msg:
        return jsonify({'error': 'not_found'}), 404

    if me.id not in (msg.sender_id, msg.recipient_id):
        return jsonify({'error': 'forbidden'}), 403

    existing = MessageDeletion.query.filter_by(user_id=me.id, message_id=msg.id).first()
    if existing:
        return jsonify({'ok': True})

    db.session.add(MessageDeletion(user_id=me.id, message_id=msg.id))
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/message/<int:message_id>/delete_for_everyone', methods=['POST'])
def api_message_delete_for_everyone(message_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    msg = _db_get(Message, message_id)
    if not msg:
        return jsonify({'error': 'not_found'}), 404

    if me.id not in (msg.sender_id, msg.recipient_id):
        return jsonify({'error': 'forbidden'}), 403

    if not _can_delete_for_everyone(me, msg):
        return jsonify({'error': 'too_late'}), 403

    # Remove attachment file if present
    fn = getattr(msg, 'attachment_filename', None)
    if fn:
        if not _is_media_file(fn):
            try:
                p = _uploads_dir() / fn
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    msg.deleted_for_all = True
    msg.edited_at = None
    msg.content = encrypt_text('')
    msg.attachment_filename = None
    msg.attachment_original = None
    msg.attachment_mime = None
    msg.attachment_size = None
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/message/<int:message_id>/edit', methods=['POST'])
def api_message_edit(message_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    msg = _db_get(Message, message_id)
    if not msg:
        return jsonify({'error': 'not_found'}), 404

    if me.id not in (msg.sender_id, msg.recipient_id):
        return jsonify({'error': 'forbidden'}), 403

    if not _can_edit_message(me, msg):
        return jsonify({'error': 'too_late'}), 403

    payload = request.get_json(silent=True) or {}
    try:
        content = (_payload_text_field(payload, 'content') or '').strip()
    except Exception:
        return jsonify({'error': 'invalid_transport_payload'}), 400
    has_attachment = bool(getattr(msg, 'attachment_filename', None))
    if not content and not has_attachment:
        return jsonify({'error': 'empty_message'}), 400
    if len(content) > 2000:
        return jsonify({'error': 'message_too_long'}), 400

    msg.content = encrypt_text(content)
    msg.edited_at = _utcnow()
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/message/<int:message_id>/star', methods=['POST'])
def api_message_star(message_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    msg = _db_get(Message, message_id)
    if not msg:
        return jsonify({'error': 'not_found'}), 404
    if me.id not in (msg.sender_id, msg.recipient_id):
        return jsonify({'error': 'forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    star = bool(payload.get('star'))

    existing = MessageStar.query.filter_by(user_id=me.id, message_id=msg.id).first()
    if star:
        if not existing:
            db.session.add(MessageStar(user_id=me.id, message_id=msg.id))
            db.session.commit()
    else:
        if existing:
            db.session.delete(existing)
            db.session.commit()

    return jsonify({'ok': True, 'starred': star})


@app.route('/api/message/<int:message_id>/pin', methods=['POST'])
def api_message_pin(message_id: int):
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    msg = _db_get(Message, message_id)
    if not msg:
        return jsonify({'error': 'not_found'}), 404
    if me.id not in (msg.sender_id, msg.recipient_id):
        return jsonify({'error': 'forbidden'}), 403

    payload = request.get_json(silent=True) or {}
    pin = bool(payload.get('pin'))

    existing = MessagePin.query.filter_by(user_id=me.id, message_id=msg.id).first()
    if pin:
        if not existing:
            db.session.add(MessagePin(user_id=me.id, message_id=msg.id))
            db.session.commit()
    else:
        if existing:
            db.session.delete(existing)
            db.session.commit()

    return jsonify({'ok': True, 'pinned': pin})


@app.route('/api/contacts/remove', methods=['POST'])
def api_contacts_remove():
    """Disconnect (remove) a contact connection so users can no longer chat."""
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    payload = request.get_json(silent=True) or {}
    username = (payload.get('username') or '').strip()
    if not username:
        return jsonify({'error': 'missing_username'}), 400

    other = _find_user_by_username(username)
    if not other:
        return jsonify({'error': 'user_not_found'}), 404
    if other.id == me.id:
        return jsonify({'error': 'cannot_remove_self'}), 400

    deleted = _delete_contact_relation(me.id, other.id)
    if deleted:
        db.session.commit()
    return jsonify({'ok': True, 'removed': bool(deleted)})


@app.route('/api/chats/<string:other_username>/clear_for_me', methods=['POST'])
def api_chat_clear_for_me(other_username: str):
    """Hide the entire conversation for the current user (delete-for-me in bulk)."""
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    other_username = (other_username or '').strip()
    other = _find_user_by_username(other_username)
    if not other:
        return jsonify({'error': 'user_not_found'}), 404

    is_self = other.id == me.id
    if not is_self and not _is_accepted_contact(me.id, other.id):
        return jsonify({'error': 'not_a_contact'}), 403

    q = Message.query
    if is_self:
        q = q.filter(Message.sender_id == me.id, Message.recipient_id == me.id)
    else:
        q = q.filter(
            db.or_(
                db.and_(Message.sender_id == me.id, Message.recipient_id == other.id),
                db.and_(Message.sender_id == other.id, Message.recipient_id == me.id),
            )
        )

    ids = [mid for (mid,) in q.with_entities(Message.id).all()]
    if not ids:
        return jsonify({'ok': True, 'cleared': 0})

    # If the messages are hidden, also drop any stars/pins for this chat for the current user.
    MessageStar.query.filter(MessageStar.user_id == me.id, MessageStar.message_id.in_(ids)).delete(synchronize_session=False)
    MessagePin.query.filter(MessagePin.user_id == me.id, MessagePin.message_id.in_(ids)).delete(synchronize_session=False)

    existing = {
        d.message_id
        for d in MessageDeletion.query
        .filter(MessageDeletion.user_id == me.id, MessageDeletion.message_id.in_(ids))
        .all()
    }
    to_add = [mid for mid in ids if mid not in existing]
    for mid in to_add:
        db.session.add(MessageDeletion(user_id=me.id, message_id=mid))
    db.session.commit()

    return jsonify({'ok': True, 'cleared': len(to_add)})


@app.route('/api/chats/clear_all_for_me', methods=['POST'])
def api_chats_clear_all_for_me():
    """Hide ALL messages involving the current user (delete-for-me in bulk)."""
    me = _get_me()
    if not me:
        return jsonify({'error': 'not_authenticated'}), 401

    ids = [
        mid
        for (mid,) in (
            Message.query
            .filter(db.or_(Message.sender_id == me.id, Message.recipient_id == me.id))
            .with_entities(Message.id)
            .all()
        )
    ]
    if not ids:
        return jsonify({'ok': True, 'cleared': 0})

    # Clean up per-user metadata as well.
    MessageStar.query.filter(MessageStar.user_id == me.id, MessageStar.message_id.in_(ids)).delete(synchronize_session=False)
    MessagePin.query.filter(MessagePin.user_id == me.id, MessagePin.message_id.in_(ids)).delete(synchronize_session=False)

    existing = {
        d.message_id
        for d in (
            MessageDeletion.query
            .filter(MessageDeletion.user_id == me.id, MessageDeletion.message_id.in_(ids))
            .all()
        )
    }
    to_add = [mid for mid in ids if mid not in existing]
    for mid in to_add:
        db.session.add(MessageDeletion(user_id=me.id, message_id=mid))
    db.session.commit()

    return jsonify({'ok': True, 'cleared': len(to_add)})


@app.route('/dashboard')
def dashboard():
    username = session.get('username')
    if not username:
        return redirect(url_for('login'))
    return render_template('dashboard.html', username=username)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('front'))



# ------------------ RUN ------------------

if __name__ == '__main__':
    _ensure_db_create_all()
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST")
    if not host:
        host = "0.0.0.0" if PRODUCTION else "127.0.0.1"
    app.run(host=host, debug=debug, port=port)
#regiter data to database pass check and button fix login route fix
