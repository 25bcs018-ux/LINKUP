"""Example custom NOVA provider (HTTP inference server).

Run this in a separate terminal/process if you want to keep your model isolated.

Start:
  python3 nova_http_server_example.py

Configure LinkUp:
  export NOVA_PROVIDER=http
  export NOVA_HTTP_ENDPOINT=http://127.0.0.1:5055/v1/nova

Optional:
  export NOVA_HTTP_AUTH="Bearer dev-token"

This is an example only; replace the reply logic with your neural network + NLP.
"""

from __future__ import annotations

import os

from flask import Flask, jsonify, request

app = Flask(__name__)


@app.post("/v1/nova")
def nova_infer():
    auth_required = (os.environ.get("NOVA_HTTP_AUTH") or "").strip()
    if auth_required:
        got = (request.headers.get("Authorization") or "").strip()
        if got != auth_required:
            return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    me_username = str(payload.get("me_username") or "user")
    user_text = str(payload.get("user_text") or "").strip()
    history = payload.get("history") or []

    # TODO: Replace with your model inference.
    if not user_text:
        reply = "Send a message and I’ll respond."
    else:
        # Example: use a tiny bit of context if present.
        last_turns = [m.get("content", "") for m in history[-4:] if isinstance(m, dict)]
        ctx = " | ".join([t.strip() for t in last_turns if t.strip()])
        reply = f"({me_username}) {user_text}" + (f"\n\nContext: {ctx}" if ctx else "")

    return jsonify({"reply": reply})


if __name__ == "__main__":
    host = os.environ.get("NOVA_HTTP_SERVER_HOST", "127.0.0.1")
    port = int(os.environ.get("NOVA_HTTP_SERVER_PORT", "5055"))
    app.run(host=host, port=port, debug=True)
