"""Example custom NOVA provider (Python hook).

Use this file as a starting point for your own neural-network/NLP stack.

Enable:
  export NOVA_PROVIDER=python
  export NOVA_PY_MODULE=nova_custom_example
  export NOVA_PY_FUNC=generate

Contract:
  def generate(*, me_username: str, user_text: str, history: list[dict]) -> str

Notes:
- Keep this function fast; the chat request is synchronous.
- If you want streaming tokens, we can add SSE/WebSocket later.
"""

from __future__ import annotations

from typing import Dict, List


def generate(*, me_username: str, user_text: str, history: List[Dict[str, str]]) -> str:
    text = (user_text or "").strip()

    # TODO: Replace this with your model inference.
    # Example sketch:
    #   features = your_tokenizer(text, history)
    #   output_ids = your_model.generate(features)
    #   return your_detokenizer(output_ids)

    if not text:
        return "Say something and I’ll respond."

    low = text.lower()
    if low.startswith("/help"):
        return (
            "Custom NOVA provider is active.\n"
            "Wire your neural-net inference inside nova_custom_example.generate()."
        )

    # A tiny, deterministic fallback so the app always replies.
    recent = ""
    if history:
        last_user = next((m for m in reversed(history) if m.get("role") == "user"), None)
        if last_user:
            recent = (last_user.get("content") or "").strip()

    if recent and recent != text:
        return f"({me_username}) You said: {text}\nEarlier you said: {recent}"

    return f"({me_username}) You said: {text}"
