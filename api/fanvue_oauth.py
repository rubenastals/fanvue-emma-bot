"""
Fanvue OAuth 2.0 helpers (authorization code + PKCE, token refresh).

Tokens are persisted to FANVUE_TOKEN_FILE so the bot survives restarts.
"""
import base64
import hashlib
import json
import os
import secrets
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from config import config
from db import oauth_store

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(_ROOT, config.FANVUE_TOKEN_FILE)
PENDING_FILE = os.path.join(_ROOT, ".oauth_pending.json")


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
    oauth_store.save_tokens(tokens)


def load_tokens() -> Optional[Dict[str, Any]]:
    return oauth_store.load_tokens()


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
    return tokens


def refresh_access_token(refresh_token: str) -> Dict[str, Any]:
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
    response.raise_for_status()
    tokens = response.json()
    _save_tokens(tokens)
    return tokens


def refresh_if_expired_or_forced(force: bool = False) -> str:
    stored = load_tokens()
    if not stored:
        raise RuntimeError("No Fanvue tokens found.")
    if force or time.time() >= stored.get("expires_at", 0) - 300:
        if not stored.get("refresh_token"):
            raise RuntimeError("Token expired and no refresh token.")
        stored = refresh_access_token(stored["refresh_token"])
    return stored["access_token"]


def get_valid_access_token() -> str:
    """Return a valid access token, refreshing automatically if needed."""
    if not load_tokens():
        raise RuntimeError(
            "No Fanvue tokens found. Run: python scripts/oauth_login.py"
        )
    return refresh_if_expired_or_forced(force=False)
