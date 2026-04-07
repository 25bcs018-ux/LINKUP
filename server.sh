#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

# Load local env file if present (DO NOT COMMIT secrets; .env is gitignored).
if [[ -f ".env" ]]; then
	set -a
	source ".env"
	set +a
fi

# One-command bootstrap + run.
# - Creates .venv if missing
# - Installs requirements
# - Ensures runtime folders + DB tables

PY_SYS="python3"

if [[ ! -x ".venv/bin/python" ]]; then
	echo "Creating venv in .venv …"
	"$PY_SYS" -m venv .venv
fi

# Prefer the workspace venv if present.
PY=".venv/bin/python"

echo "Using python: $PY"

# Install deps (idempotent). Set LINKUP_SKIP_INSTALL=1 to skip.
if [[ "${LINKUP_SKIP_INSTALL:-0}" != "1" ]]; then
	echo "Installing dependencies …"
	"$PY" -m pip install -r requirements.txt
fi

# Hackathon/demo defaults (can be overridden by exporting env vars).
export FLASK_DEBUG="${FLASK_DEBUG:-0}"
export PORT="${PORT:-8000}"
export EMAIL_VERIFY_REQUIRED="${EMAIL_VERIFY_REQUIRED:-1}"
export LINKUP_CREATE_TABLES="${LINKUP_CREATE_TABLES:-1}"

# Make sure runtime folders exist.
mkdir -p "instance/uploads" "static/avatars"

# Provide a stable demo encryption key unless one is set.
# This avoids decryption breaking across restarts during demos.
if [[ -z "${CHAT_ENC_KEY:-}" ]]; then
	mkdir -p "instance"
	if [[ -f "instance/.demo_enc_key" ]]; then
		export CHAT_ENC_KEY="$(cat instance/.demo_enc_key)"
	else
		export CHAT_ENC_KEY="$($PY - <<'PY'
import base64, os
print(base64.urlsafe_b64encode(os.urandom(32)).decode('ascii').rstrip('='))
PY
)"
		echo -n "$CHAT_ENC_KEY" > "instance/.demo_enc_key"
	fi
fi

echo "LinkUp starting on http://127.0.0.1:$PORT"
echo "EMAIL_VERIFY_REQUIRED=$EMAIL_VERIFY_REQUIRED"
echo "LINKUP_CREATE_TABLES=$LINKUP_CREATE_TABLES"

exec "$PY" app.py
