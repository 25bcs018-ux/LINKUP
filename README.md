# LinkUp (CHATS)

LinkUp is a Flask + SQLite chat app with:

- A **contact-request handshake** (reduces spam; no unsolicited DMs)
- **Encrypted-at-rest** messages (stored encrypted in the DB)
- **Group chats** with **majority-vote governance** for adding/removing members
- A built-in AI assistant (**NOVA**) that can run offline or connect to real LLMs

## Screens / Pages

- Landing: `/`
- LinkUp Secure landing: `/linkup-secure/`
- Register: `/register`
- Login: `/login`
- Chats UI: `/chats`

## Quickstart (recommended)

This repo includes a one-command runner that bootstraps a venv, installs dependencies, ensures runtime folders exist, and starts the app:

```bash
./server.sh
```

Then open:

- `http://127.0.0.1:8000`

## How it works

### Contacts handshake

You can only message users after a request is accepted.

### Encrypted-at-rest messages

Message encryption lives in `crypto.py` and is applied in `app.py`.

Storage format:

- Default: `v3:<base64url(nonce || ciphertext+tag)>` using AES-GCM
- Backward compatibility:
	- `v2:` remains decryptable for rows created with the older custom scheme.
	- Plaintext rows (no prefix) are treated as legacy plaintext.
	- `v1:` is legacy-only.

Key management:

- Recommended: set `CHAT_ENC_KEY` (base64url-encoded 32 bytes)
- Generate a key:

```bash
python3 -m crypto gen-key
```

### Groups + governance (majority vote)

LinkUp supports group chats with invite-based membership.

UI flow:

- Create: click **+ Create group** in the sidebar.
- Accept invites: open **Requests** → **Group requests** → **Accept**.
- Settings: inside a group, click **⋮** (Group settings).
- Add members (after creation): in **Group settings**, use **Add members** → `+` to start a vote.
- Exit: in **Group settings**, use **Exit** (always allowed).

Governance rules:

- Invitations sent during initial group creation are allowed immediately (the server issues a short-lived `creation_token` for that creation session).
- After the group is created, **adding** or **removing** members requires a **Yes/No poll**.
- If **Yes** reaches a majority of current members, the action executes automatically.
- There are **no admins** and no manual **delete group** action; the group is deleted automatically only when the **last member exits**.

### Built-in AI assistant (NOVA)

NOVA is available inside the chats UI (floating widget). It is implemented as a normal user + encrypted message rows, with special routing so it doesn't require contact acceptance.

By default NOVA is offline (rule-based). You can connect it to real models via environment variables.

OpenAI (cloud):

```bash
export NOVA_PROVIDER=openai
export OPENAI_API_KEY="..."
export OPENAI_MODEL="gpt-4o-mini"
```

Ollama (local):

```bash
export NOVA_PROVIDER=ollama
export OLLAMA_MODEL="llama3.1"
# optional
export OLLAMA_HOST="http://localhost:11434"
```

Custom model (Python module):

```bash
export NOVA_PROVIDER=python
export NOVA_PY_MODULE=nova_custom_example
export NOVA_PY_FUNC=generate
```

Custom model (HTTP server):

```bash
export NOVA_PROVIDER=http
export NOVA_HTTP_ENDPOINT="http://127.0.0.1:5055/v1/nova"
# optional
export NOVA_HTTP_AUTH="Bearer dev-token"
```

Tuning:

```bash
export NOVA_TEMPERATURE=0.4
export NOVA_MAX_TOKENS=220
export NOVA_MAX_HISTORY=12
export NOVA_DB_HISTORY=18
export NOVA_HTTP_TIMEOUT=20
```

Disable NOVA:

```bash
export NOVA_ENABLED=0
```

## API (high level)

Contacts:

- `GET /api/contacts/inbox`
- `GET /api/contacts/sent`
- `POST /api/contacts/request`
- `POST /api/contacts/accept`
- `POST /api/contacts/withdraw`

Direct messages:

- `GET /api/messages/<other_username>`
- `POST /api/messages/<other_username>`

Groups:

- `POST /api/groups/create` (returns a short-lived `creation_token`)
- `POST /api/groups/<group_id>/invite` (may start/continue an invite poll)
- `POST /api/groups/<group_id>/members/remove` (starts a removal poll)
- `GET /api/groups/<group_id>/polls`
- `POST /api/groups/polls/<poll_id>/vote`

## Run (manual)

Development:

```bash
python3 -m pip install -r requirements.txt
export CHAT_ENC_KEY="<paste generated key>"   # recommended
python3 app.py
```

Production (example with Gunicorn):

```bash
python3 -m pip install -r requirements.txt
export LINKUP_ENV=production
export SECRET_KEY="change-me"
export CHAT_ENC_KEY="<32-byte base64url key>"
export DATABASE_URL="postgresql://user:pass@host:5432/linkup"  # or sqlite:///LINKUP.db
export LINKUP_CREATE_TABLES=0
export PORT=8000
gunicorn -c gunicorn.conf.py wsgi:app
```

Notes:

- SQLite is fine for demos/small usage. For real production, switch to Postgres.
- Use HTTPS + secure cookies behind a reverse proxy.

## Email verification (recommended)

In production (`LINKUP_ENV=production`), email verification defaults to **ON**.

Configure SMTP via env vars:

- `SMTP_HOST`, `SMTP_PORT`
- `SMTP_USER`, `SMTP_PASS`
- `SMTP_FROM`

If `EMAIL_VERIFY_REQUIRED=1` and SMTP is not configured, the app will refuse to start in production to avoid a broken registration flow.

### SMTP smoke test

Before deploying, you can confirm SMTP works locally:

```bash
export SMTP_HOST=...
export SMTP_PORT=587
export SMTP_USER=...
export SMTP_PASS=...
export SMTP_FROM=...
python3 scripts/send_test_email.py you@yourmail.com
```

If this succeeds, LinkUp OTP emails will send.

## Google sign-in

Enable “Continue with Google” by setting:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`

Google OAuth callback URL (configure this in Google Cloud Console):

- `https://<your-domain>/auth/google/callback`

If your platform requires an explicit callback URL override, set:

- `GOOGLE_REDIRECT_URI=https://<your-domain>/auth/google/callback`

## Email OTP login

LinkUp uses a **6-digit OTP for email verification after signup**.

Config:

- `VERIFY_OTP_TTL_SECONDS` (or `OTP_TTL_SECONDS`) (default 600)
- Requires SMTP in production when `EMAIL_VERIFY_REQUIRED=1`



## Deploy to the internet (VPS)

This is the simplest “real server” setup: Gunicorn + systemd + Nginx.

1) Copy files to your server


```bash
cd /var/www/linkup
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

2) Create your production env file

Create `/etc/linkup.env` manually (example):

```bash
sudo nano /etc/linkup.env
```

Minimum recommended variables:

- `LINKUP_ENV=production`
- `SECRET_KEY=...`
- `CHAT_ENC_KEY=...`
- `DATABASE_URL=...` (or `sqlite:///LINKUP.db` for small demos)
- `LINKUP_CREATE_TABLES=0`
- If `EMAIL_VERIFY_REQUIRED=1`: set SMTP vars (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`)

3) Systemd service


4) Nginx reverse proxy


5) HTTPS


## Deploy to the internet (PaaS)

This repo includes a `Procfile`, so platforms that support it can run:

`gunicorn -c gunicorn.conf.py wsgi:app`

Set these environment variables in your platform dashboard:

- `LINKUP_ENV=production`
- `SECRET_KEY=...`
- `CHAT_ENC_KEY=...`
- `DATABASE_URL=...`
- `LINKUP_CREATE_TABLES=0`

## Deploy on PythonAnywhere

This project is ready for PythonAnywhere with a WSGI app + static file mappings.

### 1) Upload code and create venv

In a PythonAnywhere Bash console:

```bash
cd ~
git clone <your-repo-url> LINKUP
cd LINKUP
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Create runtime folders

```bash
mkdir -p ~/LINKUP/instance/uploads
mkdir -p ~/LINKUP/static/avatars
```

### 3) Set environment variables in your PythonAnywhere WSGI file

Use strong production values:

- `LINKUP_ENV=production`
- `SECRET_KEY=<strong-random-secret>`
- `CHAT_ENC_KEY=<base64url-32-byte-key>`
- `LINKUP_CREATE_TABLES=1` for first deploy, then set to `0`
- Optional SQLite: `DATABASE_URL=sqlite:////home/<username>/LINKUP/instance/LINKUP.db`
- If email verification is required: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SMTP_FROM`

Use the provided template file `pythonanywhere_wsgi.py` as the content for:

- `/var/www/<username>_pythonanywhere_com_wsgi.py`

Then update `USERNAME` and `PROJECT_DIR` values inside that file.

### 4) Configure Web app static mappings

In PythonAnywhere Web tab, add:

- URL: `/static/` -> Directory: `/home/<username>/LINKUP/static/`
- URL: `/linkup-secure/static/` -> Directory: `/home/<username>/LINKUP/linkup_secure/static/`

### 5) Reload app

Click **Reload** in PythonAnywhere Web tab.

### 6) First-run DB creation toggle

If using SQLite and no migrations:

1. Set `LINKUP_CREATE_TABLES=1` in WSGI env block.
2. Reload once to create tables.
3. Set `LINKUP_CREATE_TABLES=0`.
4. Reload again.

### 7) Quick smoke test

- Open `/login` and `/register`
- Open `/chats`
- Send direct message and verify auto-refresh
- Verify NOVA opens and responds
- Verify sidebar unread badges update

## Tests

```bash
python3 -m unittest -v
```
