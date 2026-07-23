"""
Fanvue OAuth 2.0 helpers (authorization code + PKCE, token refresh).

Fanvue refresh tokens ROTATE and are SINGLE-USE (30s grace for retries).
Concurrent refreshes after that window invalidate the whole chain — the usual
reason bots "randomly" need re-Authorize. We serialise refresh with a lock.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from config import config
from db import oauth_store

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(_ROOT, config.FANVUE_TOKEN_FILE)
PENDING_FILE = os.path.join(_ROOT, ".oauth_pending.json")

# Single-flight refresh (process-local). Redis lock added when available.
_refresh_lock = threading.Lock()
_refresh_inflight: Optional[threading.Event] = None
_cached: Optional[Dict[str, Any]] = None  # in-process mirror after successful load/refresh
_REFRESH_SKEW_SEC = int(os.getenv("OAUTH_REFRESH_SKEW_SEC", "600"))  # refresh 10m early
_REDIS_LOCK_KEY = "oauth_refresh_lock"
_REDIS_LOCK_TTL = 45


def _redis_lock_key() -> str:
    from db import account_id

    return f"oauth_refresh_lock:{account_id()}"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def generate_pkce() -> Dict[str, str]:
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("utf-8")).digest())
    return {"code_verifier": verifier, "code_challenge": challenge}


def build_authorization_url(state: str, code_challenge: str) -> str:
    params = {
        "client_id": config.FANVUE_CLIENT_ID,
        "redirect_uri": config.FANVUE_REDIRECT_URI,
        "response_type": "code",
        "scope": config.FANVUE_OAUTH_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{config.FANVUE_AUTH_URL}?{urlencode(params)}"


def _basic_auth_header() -> str:
    raw = f"{config.FANVUE_CLIENT_ID}:{config.FANVUE_CLIENT_SECRET}"
    return base64.b64encode(raw.encode("utf-8")).decode("utf-8")


def _save_tokens(tokens: Dict[str, Any]) -> None:
    global _cached
    oauth_store.save_tokens(tokens)
    # Keep process cache in sync (always re-load normalised shape)
    _cached = oauth_store.load_tokens()


def load_tokens() -> Optional[Dict[str, Any]]:
    global _cached
    # Prefer fresh PG/file; cache only as fast path if still valid
    stored = oauth_store.load_tokens()
    if stored:
        _cached = stored
    return stored


def save_pending_oauth(state: str, code_verifier: str) -> None:
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        json.dump({"state": state, "code_verifier": code_verifier}, f)


def load_pending_oauth() -> Optional[Dict[str, str]]:
    if not os.path.exists(PENDING_FILE):
        return None
    with open(PENDING_FILE, encoding="utf-8") as f:
        return json.load(f)


def clear_pending_oauth() -> None:
    if os.path.exists(PENDING_FILE):
        os.remove(PENDING_FILE)


def exchange_code_for_tokens(code: str, code_verifier: str) -> Dict[str, Any]:
    response = requests.post(
        config.FANVUE_TOKEN_URL,
        headers={
            "Authorization": f"Basic {_basic_auth_header()}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.FANVUE_REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    response.raise_for_status()
    tokens = response.json()
    _save_tokens(tokens)
    try:
        from core.oauth_rescue import clear_broken

        clear_broken()
    except Exception:
        pass
    print(
        f"   🔐 OAuth: new tokens saved "
        f"(expires_in={tokens.get('expires_in')}, "
        f"has_refresh={bool(tokens.get('refresh_token'))})",
        flush=True,
    )
    return tokens


def _acquire_redis_lock() -> bool:
    try:
        from db import use_redis
        from db import redis_client

        if not use_redis():
            return True  # no redis → rely on threading lock only
        r = redis_client.get_redis()
        # SET NX EX — only one refresh across replicas
        return bool(r.set(_redis_lock_key(), str(time.time()), nx=True, ex=_REDIS_LOCK_TTL))
    except Exception:
        return True


def _release_redis_lock() -> None:
    try:
        from db import use_redis
        from db import redis_client

        if use_redis():
            redis_client.get_redis().delete(_redis_lock_key())
    except Exception:
        pass


def _do_refresh_http(refresh_token: str) -> Dict[str, Any]:
    response = requests.post(
        config.FANVUE_TOKEN_URL,
        headers={
            "Authorization": f"Basic {_basic_auth_header()}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    if not response.ok:
        detail = (response.text or "")[:180]
        try:
            from core.oauth_rescue import OAuthBrokenError, mark_broken

            mark_broken(f"refresh HTTP {response.status_code}: {detail}")
            raise OAuthBrokenError(
                f"Fanvue refresh failed ({response.status_code}). Re-Authorize needed."
            )
        except ImportError:
            response.raise_for_status()
    response.raise_for_status()
    tokens = response.json()
    # Fanvue ALWAYS rotates refresh_token — must persist the new one
    if not tokens.get("refresh_token"):
        # Keep old only if provider omitted (shouldn't happen on Fanvue)
        tokens["refresh_token"] = refresh_token
    _save_tokens(tokens)
    try:
        from core.oauth_rescue import clear_broken

        clear_broken()
    except Exception:
        pass
    print(
        f"   🔐 OAuth refresh OK (expires_in={tokens.get('expires_in')})",
        flush=True,
    )
    return tokens


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
    """
    Refresh with single-flight lock. Concurrent callers wait and reuse the result
    instead of burning Fanvue's single-use refresh token.
    """
    global _refresh_inflight

    # Fast path: another thread just finished — reload
    with _refresh_lock:
        current = load_tokens() or {}
        # If stored refresh already rotated away from what we were asked to use,
        # someone else won — return their tokens.
        if (
            current.get("access_token")
            and current.get("refresh_token")
            and current.get("refresh_token") != refresh_token
            and time.time() < int(current.get("expires_at") or 0) - 60
        ):
            return current

        if _refresh_inflight is not None:
            waiter = _refresh_inflight
        else:
            waiter = None
            _refresh_inflight = threading.Event()

    if waiter is not None:
        waiter.wait(timeout=_REDIS_LOCK_TTL + 5)
        stored = load_tokens()
        if not stored or not stored.get("access_token"):
            raise RuntimeError("OAuth refresh wait finished but no tokens")
        return stored

    got_redis = False
    try:
        # Wait briefly for redis lock (other replica refreshing)
        for _ in range(40):
            if _acquire_redis_lock():
                got_redis = True
                break
            time.sleep(0.25)
            # Maybe the other replica finished
            current = load_tokens() or {}
            if (
                current.get("refresh_token")
                and current.get("refresh_token") != refresh_token
                and time.time() < int(current.get("expires_at") or 0) - 60
            ):
                return current
        if not got_redis:
            # Proceed anyway with thread lock (better than stall forever)
            print("   ⚠️ OAuth: redis refresh lock busy — proceeding carefully", flush=True)

        # Re-read: another replica may have rotated already
        current = load_tokens() or {}
        if (
            current.get("refresh_token")
            and current.get("refresh_token") != refresh_token
            and time.time() < int(current.get("expires_at") or 0) - 60
        ):
            return current
        use_rt = current.get("refresh_token") or refresh_token
        return _do_refresh_http(use_rt)
    finally:
        if got_redis:
            _release_redis_lock()
        with _refresh_lock:
            if _refresh_inflight is not None:
                _refresh_inflight.set()
                _refresh_inflight = None


def refresh_if_expired_or_forced(force: bool = False) -> str:
    stored = load_tokens()
    if not stored:
        try:
            from core.oauth_rescue import OAuthBrokenError, mark_broken

            mark_broken("no_tokens")
            raise OAuthBrokenError("No Fanvue tokens found.")
        except ImportError:
            raise RuntimeError("No Fanvue tokens found.")

    expires_at = int(stored.get("expires_at") or 0)
    needs_refresh = force or time.time() >= expires_at - _REFRESH_SKEW_SEC
    if not needs_refresh:
        return stored["access_token"]

    if not stored.get("refresh_token"):
        try:
            from core.oauth_rescue import OAuthBrokenError, mark_broken

            mark_broken("no_refresh_token")
            raise OAuthBrokenError("Token expired and no refresh token.")
        except ImportError:
            raise RuntimeError("Token expired and no refresh token.")

    stored = refresh_access_token(stored["refresh_token"])
    return stored["access_token"]


def get_valid_access_token() -> str:
    """Return a valid access token, refreshing automatically if needed."""
    try:
        from core.oauth_rescue import OAuthBrokenError, is_broken

        if is_broken():
            raise OAuthBrokenError(
                "OAuth in backoff after refresh failure — waiting for re-auth."
            )
    except ImportError:
        pass
    if not load_tokens():
        raise RuntimeError(
            "No Fanvue tokens found. Run: python scripts/oauth_login.py"
        )
    return refresh_if_expired_or_forced(force=False)
