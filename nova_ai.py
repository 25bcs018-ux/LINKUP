import os
import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _provider() -> str:
    # openai: OpenAI Chat Completions via REST
    # ollama: local Ollama server (http://localhost:11434)
    # http: custom HTTP inference endpoint
    # python: custom local Python module hook
    # local: no external calls
    return (os.environ.get("NOVA_PROVIDER", "local") or "local").strip().lower()


def _system_prompt() -> str:
    base = (
        "You are NOVA, the built-in AI assistant inside the LinkUp chat app. "
        "Be helpful, concise, and practical. Ask clarifying questions when needed. "
        "Respect user privacy. Do not request passwords, API keys, or other secrets. "
        "If the user asks for illegal or harmful instructions, refuse briefly. "
        "Prefer short, actionable steps. For troubleshooting, propose checks in order."
    )

    # LinkUp-specific context so NOVA can answer product/dev questions about this app.
    # Kept short to avoid blowing up provider payload size.
    kb = _linkup_help_context()
    if not kb:
        return base

    return (
        base
        + "\n\n"
        + "LINKUP TECHNICAL CONTEXT (authoritative):\n"
        + kb
        + "\n\n"
        + "Rules when answering about LinkUp:\n"
        + "- Prefer these docs over guessing.\n"
        + "- If the answer is not in the context, say you’re not sure and suggest where to look (README/app.py/templates).\n"
        + "- Don’t invent endpoints, settings, or UI that isn’t described."
    )


_HELP_CACHE: Optional[str] = None


def _read_repo_file(rel_path: str) -> str:
    try:
        here = Path(__file__).resolve().parent
        p = (here / rel_path).resolve()
        if not p.exists() or not p.is_file():
            return ""
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _linkup_ui_notes() -> str:
    # Keep in sync with the current UI in templates/chats.html.
    return (
        "UI notes (current build):\n"
        "- NOVA opens from a floating widget in Chats (mobile + desktop).\n"
        "- On mobile, the chat layout can be compact with a persistent contact sidebar.\n"
        "- Requests and Settings are opened from Menu (Requests badge may appear there).\n"
        "- Group membership changes use polls (Yes/No). Removal polls exclude the subject from voting.\n"
    )


def _linkup_help_context() -> str:
    """Small, cached help context for LinkUp.

    Source of truth is README.md plus a tiny UI note block for recent UX.
    """
    global _HELP_CACHE
    if _HELP_CACHE is not None:
        return _HELP_CACHE

    enabled = _env_bool("NOVA_LINKUP_HELP", True)
    if not enabled:
        _HELP_CACHE = ""
        return _HELP_CACHE

    readme = _read_repo_file("README.md")
    # Clip README aggressively; it can be long.
    readme = (readme or "").strip()
    if readme:
        readme = _clip(readme, int(os.environ.get("NOVA_LINKUP_HELP_CHARS", "2600") or "2600"))

    notes = _linkup_ui_notes().strip()
    parts = [p for p in (notes, readme) if p]
    _HELP_CACHE = "\n\n".join(parts).strip()
    return _HELP_CACHE


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")


def _sanitize_reply(text: str) -> str:
    out = (text or "").strip()
    if not out:
        return ""
    # Keep replies compact for chat UX.
    out = _clip(out, int(os.environ.get("NOVA_REPLY_MAX_CHARS", "1200") or "1200"))
    return out


def _normalize_history(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    max_history = int(os.environ.get("NOVA_MAX_HISTORY", "12") or "12")
    if max_history <= 0:
        return []

    cleaned: List[Dict[str, str]] = []
    for m in history[-max_history:]:
        role = (m.get("role") or "").strip()
        content = (m.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        cleaned.append({"role": role, "content": _clip(content, 1400)})
    return cleaned


def _last_user_turn(history: List[Dict[str, str]]) -> str:
    for m in reversed(history):
        if m.get("role") == "user":
            return (m.get("content") or "").strip()
    return ""


def _local_guided_reply(*, me_username: str, user_text: str, history: List[Dict[str, str]]) -> str:
    text = (user_text or "").strip()
    low = text.lower()
    prev_user = _last_user_turn(history[:-1]) if history else ""

    if not text:
        return "Tell me your goal in one line, and I will give step-by-step help."

    if low in ("hi", "hello", "hey", "yo", "hola"):
        return (
            f"Hi {me_username}. I can help with LinkUp setup, chats, groups, NOVA, and debugging.\n"
            "Try: 'how do I fix mobile sidebar taps?'"
        )

    if low.startswith("/help") or low == "help":
        return (
            "NOVA quick help:\n"
            "1. Ask how-to questions: 'how to add a contact'\n"
            "2. Ask debug questions: 'why is sidebar tap not working'\n"
            "3. Ask app questions: '/linkup' or '/privacy'"
        )

    followup = low.startswith(("and ", "also ", "what about", "then ", "next "))
    if followup and prev_user:
        return (
            "Got it, continuing from your previous question.\n"
            "Share one detail: device (Android/iPhone), browser/PWA, and what happens after tap/send."
        )

    if any(k in low for k in ("bug", "error", "not working", "fails", "issue", "problem", "stuck")):
        return (
            "Let’s debug quickly:\n"
            "1. Tell me exact screen and action (for example: Chats -> tap contact).\n"
            "2. Tell me expected vs actual behavior.\n"
            "3. Tell me device + browser/PWA.\n"
            "Then I’ll give a targeted fix sequence."
        )

    if any(k in low for k in ("how do i", "how to", "steps", "guide", "walk me")):
        return (
            "Sure. I can give exact steps.\n"
            "Tell me which task: add contact, requests, create group, group polls, encryption key, or NOVA setup."
        )

    if any(k in low for k in ("nova", "assistant", "ai")):
        return (
            "NOVA can run in local mode or with providers (OpenAI/Ollama/python/http).\n"
            "If you want better answers, configure a provider; otherwise ask specific LinkUp questions and I’ll guide you."
        )

    snippet = _clip(text, 220)
    return (
        "I can help with this.\n"
        f"You said: \"{snippet}\"\n"
        "Tell me the exact outcome you want, and I’ll provide concise steps."
    )


def generate_reply(
    *,
    me_username: str,
    user_text: str,
    history: List[Dict[str, str]],
) -> str:
    """Generate a NOVA response.

    history: list of {role: 'user'|'assistant', content: str}
    """
    provider = _provider()
    clean_user_text = _clip((user_text or "").strip(), 1800)
    clean_history = _normalize_history(history)

    if not clean_user_text:
        return "Say something and I will help."

    if provider == "openai":
        return _sanitize_reply(_openai_reply(me_username=me_username, user_text=clean_user_text, history=clean_history))
    if provider == "ollama":
        return _sanitize_reply(_ollama_reply(me_username=me_username, user_text=clean_user_text, history=clean_history))
    if provider == "http":
        return _sanitize_reply(_custom_http_reply(me_username=me_username, user_text=clean_user_text, history=clean_history))
    if provider == "python":
        return _sanitize_reply(_custom_python_reply(me_username=me_username, user_text=clean_user_text, history=clean_history))
    return _sanitize_reply(_local_guided_reply(me_username=me_username, user_text=clean_user_text, history=clean_history))


def _custom_http_reply(*, me_username: str, user_text: str, history: List[Dict[str, str]]) -> str:
    """Call a custom inference server you control.

    Expected request body:
      {
        "me_username": "...",
        "system": "...",
        "history": [{"role":"user|assistant", "content":"..."}],
        "user_text": "..."
      }

    Expected response body:
      {"reply": "..."}
    """
    endpoint = (os.environ.get("NOVA_HTTP_ENDPOINT") or "").strip()
    if not endpoint:
        return ""

    timeout_s = float(os.environ.get("NOVA_HTTP_TIMEOUT", "20") or "20")
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    auth = (os.environ.get("NOVA_HTTP_AUTH") or "").strip()
    if auth:
        # e.g. "Bearer abc" or "Token xyz"
        headers["Authorization"] = auth

    payload: Dict[str, Any] = {
        "me_username": me_username,
        "system": _system_prompt(),
        "history": history,
        "user_text": user_text,
        "temperature": float(os.environ.get("NOVA_TEMPERATURE", "0.4") or "0.4"),
        "max_tokens": int(os.environ.get("NOVA_MAX_TOKENS", "220") or "220"),
    }

    try:
        r = requests.post(endpoint, headers=headers, json=payload, timeout=timeout_s)
        if r.status_code >= 400:
            return ""
        data = r.json()
        reply = (data.get("reply") or data.get("content") or "").strip()
        return reply
    except Exception:
        return ""


def _custom_python_reply(*, me_username: str, user_text: str, history: List[Dict[str, str]]) -> str:
    """Call a local Python module function.

    Env:
      NOVA_PY_MODULE=my_custom_model
      NOVA_PY_FUNC=generate  (default)

    Function signature should be:
      def generate(*, me_username: str, user_text: str, history: list[dict]) -> str
    """
    mod_name = (os.environ.get("NOVA_PY_MODULE") or "").strip()
    if not mod_name:
        return ""
    func_name = (os.environ.get("NOVA_PY_FUNC") or "generate").strip() or "generate"

    try:
        mod = importlib.import_module(mod_name)
        fn = getattr(mod, func_name, None)
        if not callable(fn):
            return ""
        out = fn(me_username=me_username, user_text=user_text, history=history)
        return (out or "").strip()
    except Exception:
        return ""


def _openai_reply(*, me_username: str, user_text: str, history: List[Dict[str, str]]) -> str:
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return ""

    model = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()
    base_url = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com").rstrip("/")

    msgs: List[Dict[str, str]] = [{"role": "system", "content": _system_prompt()}]

    for m in history:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": _clip(str(content), 1500)})

    # Ensure the latest user message is present.
    msgs.append({"role": "user", "content": f"User ({me_username}): {user_text}"})

    timeout_s = float(os.environ.get("NOVA_HTTP_TIMEOUT", "20") or "20")
    url = f"{base_url}/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    payload: Dict[str, Any] = {
        "model": model,
        "messages": msgs,
        "temperature": float(os.environ.get("NOVA_TEMPERATURE", "0.4") or "0.4"),
        "max_tokens": int(os.environ.get("NOVA_MAX_TOKENS", "220") or "220"),
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
        if r.status_code >= 400:
            return ""
        data = r.json()
        choice0 = (data.get("choices") or [{}])[0]
        msg = choice0.get("message") or {}
        content = (msg.get("content") or "").strip()
        return content
    except Exception:
        return ""


def _ollama_reply(*, me_username: str, user_text: str, history: List[Dict[str, str]]) -> str:
    model = (os.environ.get("OLLAMA_MODEL") or "llama3.1").strip()
    host = (os.environ.get("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")

    msgs: List[Dict[str, str]] = [{"role": "system", "content": _system_prompt()}]

    for m in history:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and content:
            msgs.append({"role": role, "content": _clip(str(content), 1500)})

    msgs.append({"role": "user", "content": f"User ({me_username}): {user_text}"})

    timeout_s = float(os.environ.get("NOVA_HTTP_TIMEOUT", "20") or "20")
    url = f"{host}/api/chat"
    payload: Dict[str, Any] = {
        "model": model,
        "messages": msgs,
        "stream": False,
        "options": {
            "temperature": float(os.environ.get("NOVA_TEMPERATURE", "0.4") or "0.4"),
        },
    }

    try:
        r = requests.post(url, json=payload, timeout=timeout_s)
        if r.status_code >= 400:
            return ""
        data = r.json()
        msg = data.get("message") or {}
        content = (msg.get("content") or "").strip()
        return content
    except Exception:
        return ""
