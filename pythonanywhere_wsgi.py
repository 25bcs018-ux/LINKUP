"""PythonAnywhere WSGI template for LinkUp.

Usage:
1) Copy this file content into:
   /var/www/<username>_pythonanywhere_com_wsgi.py
2) Edit USERNAME and PROJECT_DIR.
3) Set production env vars below.
4) Reload web app from PythonAnywhere dashboard.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# -------- Edit these two values --------
USERNAME = "your-pythonanywhere-username"
PROJECT_DIR = f"/home/{USERNAME}/LINKUP"
# --------------------------------------


def load_env_file(path: Path) -> None:
    """Minimal .env loader (KEY=VALUE lines, ignores comments/blank lines)."""
    if not path.exists() or not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


project_path = Path(PROJECT_DIR)
if str(project_path) not in sys.path:
    sys.path.insert(0, str(project_path))

# Optional: load local env file first (if you create one).
load_env_file(project_path / ".env")
load_env_file(project_path / ".env.production")

# Recommended production defaults (override as needed).
os.environ.setdefault("LINKUP_ENV", "production")
os.environ.setdefault("LINKUP_CREATE_TABLES", "0")
os.environ.setdefault("DATABASE_URL", f"sqlite:////home/{USERNAME}/LINKUP/instance/LINKUP.db")

# IMPORTANT: set these securely in this file or via env before import app:
# os.environ["SECRET_KEY"] = "<strong-random-secret>"
# os.environ["CHAT_ENC_KEY"] = "<base64url-32-byte-key>"

from app import app, db, PRODUCTION  # noqa: E402


# Optional first-run table creation toggle for SQLite/no-migrations setups.
with app.app_context():
    default_create = "0" if PRODUCTION else "1"
    if os.environ.get("LINKUP_CREATE_TABLES", default_create) == "1":
        db.create_all()

application = app
