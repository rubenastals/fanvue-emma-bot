"""
When Fanvue refresh dies, we cannot click Authorize for you — but we CAN:
  1) stop hammering the token endpoint
  2) alert DIGEST_WEBHOOK_URL (Discord/Slack) once
  3) mint a fresh authorize URL (+ store PKCE in Redis)
  4) optionally run a tiny callback HTTP server (Railway PORT) to finish login alone

Env:
  DIGEST_WEBHOOK_URL — Discord/Slack incoming webhook
  OAUTH_CALLBACK_HTTP=1 — start /oauth/callback listener on $PORT (needs public URL in Fanvue Builder)
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from config import config

_broken_until = 0.0
_last_notify = 0.0
_http_started = False
_NOTIFY_COOLDOWN_SEC = int(os.getenv("OAUTH_ALERT_COOLDOWN_SEC", "1800"))  # 30m
_BROKEN_BACKOFF_SEC = int(os.getenv("OAUTH_BROKEN_BACKOFF_SEC", "120"))


class OAuthBrokenError(RuntimeError):
    """Refresh/token exchange failed — needs human Authorize (or public callback)."""


def _redis():
    try:
        from db import use_redis
        from db import redis_client

        if use_redis():
            return redis_client.get_redis()
    except Exception:
        return None
    return None


def _pending_key() -> str:
    from db import account_id

    return f"oauth_pending:{account_id()}"


def _flag_key() -> str:
    from db import account_id

    return f"oauth_broken:{account_id()}"


def mark_broken(reason: str = "refresh_failed") -> None:
    global _broken_until
    _broken_until = time.time() + _BROKEN_BACKOFF_SEC
    r = _redis()
    if r is not None:
        try:
            r.setex(_flag_key(), max(_BROKEN_BACKOFF_SEC, 300), reason[:200])
        except Exception:
            pass
    print(f"   🔐 OAuth BROKEN: {reason} — backoff {_BROKEN_BACKOFF_SEC}s", flush=True)
    notify_rescue(reason)


def clear_broken() -> None:
    global _broken_until
    _broken_until = 0.0
    r = _redis()
    if r is not None:
        try:
            r.delete(_flag_key())
        except Exception:
            pass


def is_broken() -> bool:
    if time.time() < _broken_until:
        return True
    r = _redis()
    if r is not None:
        try:
            return bool(r.exists(_flag_key()))
        except Exception:
            pass
    return False


def save_pending(state: str, code_verifier: str) -> None:
    from api import fanvue_oauth

    fanvue_oauth.save_pending_oauth(state, code_verifier)
    r = _redis()
    if r is not None:
        try:
            r.setex(
                _pending_key(),
                3600,
                json.dumps({"state": state, "code_verifier": code_verifier}),
            )
        except Exception:
            pass


def load_pending() -> Optional[dict]:
    r = _redis()
    if r is not None:
        try:
            raw = r.get(_pending_key())
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    from api import fanvue_oauth

    return fanvue_oauth.load_pending_oauth()


def begin_authorize() -> str:
    """Create PKCE session + return Fanvue authorize URL."""
    from api.fanvue_oauth import build_authorization_url, generate_pkce

    pkce = generate_pkce()
    state = secrets.token_hex(16)
    save_pending(state, pkce["code_verifier"])
    return build_authorization_url(state, pkce["code_challenge"])


def _post_webhook(text: str) -> bool:
    url = (os.getenv("DIGEST_WEBHOOK_URL") or getattr(config, "DIGEST_WEBHOOK_URL", "") or "").strip()
    if not url:
        return False
    payload = json.dumps({"content": text[:1900]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "emma-oauth-rescue/1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return 200 <= getattr(resp, "status", 200) < 300
    except Exception:
        return False


def notify_rescue(reason: str = "") -> None:
    """Discord/Slack alert with authorize link (cooldown)."""
    global _last_notify
    now = time.time()
    if now - _last_notify < _NOTIFY_COOLDOWN_SEC:
        return
    _last_notify = now
    try:
        auth_url = begin_authorize()
    except Exception as e:
        auth_url = f"(could not build URL: {e})"
    redirect = getattr(config, "FANVUE_REDIRECT_URI", "") or ""
    text = (
        "🚨 **Emma Fanvue OAuth muerto** — el bot no puede leer/escribir DMs.\n"
        f"Motivo: `{reason or 'refresh_failed'}`\n\n"
        f"1) Abre y Authorize como creadora:\n{auth_url}\n\n"
        f"2) Redirect configurado: `{redirect}`\n"
        "Si es localhost: copia la URL final y pégala en Cursor / "
        "`python scripts/oauth_login.py`.\n"
        "Si el poller tiene callback HTTP público: Authorize basta — "
        "el bot completa solo."
    )
    ok = _post_webhook(text)
    print(
        f"   🔐 OAuth rescue alert → webhook={'OK' if ok else 'SKIP/FAIL'}",
        flush=True,
    )
    print(f"   🔐 Re-auth URL:\n{auth_url}", flush=True)


def finish_from_callback_url(url: str) -> bool:
    """Exchange code from a pasted/callback URL. Returns True on success."""
    from api.fanvue_oauth import clear_pending_oauth, exchange_code_for_tokens

    parsed = urlparse(url.strip())
    params = parse_qs(parsed.query)
    code = (params.get("code") or [None])[0]
    state = (params.get("state") or [None])[0]
    if not code:
        return False
    pending = load_pending()
    if not pending or pending.get("state") != state:
        # fall back to file pending
        from api import fanvue_oauth

        pending = fanvue_oauth.load_pending_oauth()
    if not pending or pending.get("state") != state:
        raise OAuthBrokenError("OAuth state mismatch — start rescue again")
    exchange_code_for_tokens(code, pending["code_verifier"])
    clear_pending_oauth()
    r = _redis()
    if r is not None:
        try:
            r.delete(_pending_key())
        except Exception:
            pass
    clear_broken()
    print("   🔐 OAuth rescue: tokens refreshed OK", flush=True)
    return True


def maybe_start_callback_http() -> None:
    """
    Background HTTP server for /oauth/callback when OAUTH_CALLBACK_HTTP=1.
    Requires Fanvue Builder redirect = https://<public-host>/oauth/callback
    and Railway public networking on the poller service.
    """
    global _http_started
    if _http_started:
        return
    if os.getenv("OAUTH_CALLBACK_HTTP", "0") != "1":
        return
    port = int(os.getenv("PORT") or os.getenv("OAUTH_CALLBACK_PORT") or "0")
    if port <= 0:
        print("   🔐 OAUTH_CALLBACK_HTTP=1 but no PORT — skip HTTP callback")
        return

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: A003
            return

        def do_GET(self):  # noqa: N802
            if not self.path.startswith("/oauth/callback"):
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"not found")
                return
            try:
                full = f"http://local{self.path}"
                finish_from_callback_url(full)
                body = b"Fanvue connected. Emma can chat again. You can close this tab."
                self.send_response(200)
            except Exception as e:
                body = f"OAuth failed: {e}".encode("utf-8")
                self.send_response(400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

    def _run():
        try:
            httpd = HTTPServer(("0.0.0.0", port), Handler)
            print(f"   🔐 OAuth callback HTTP on :{port}/oauth/callback", flush=True)
            httpd.serve_forever()
        except Exception as e:
            print(f"   ⚠️ OAuth callback HTTP failed: {e}", flush=True)

    _http_started = True
    threading.Thread(target=_run, daemon=True).start()
