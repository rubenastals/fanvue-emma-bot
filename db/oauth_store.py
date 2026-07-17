"""OAuth token persistence — Postgres when DATABASE_URL set, else JSON file."""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from sqlalchemy import text

from config import config
from db import account_id, use_postgres

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(_ROOT, config.FANVUE_TOKEN_FILE)


def _file_load() -> Optional[Dict[str, Any]]:
    if not os.path.exists(TOKEN_FILE):
        return None
    with open(TOKEN_FILE, encoding="utf-8") as f:
        return json.load(f)


def _file_save(payload: Dict[str, Any]) -> None:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def load_tokens(aid: Optional[str] = None) -> Optional[Dict[str, Any]]:
    aid = aid or account_id()
    if not use_postgres():
        return _file_load()
    from db.pg import session_scope

    with session_scope() as session:
        row = session.execute(
            text(
                """
                SELECT access_token, refresh_token, expires_at, scope, token_type
                FROM oauth_tokens WHERE account_id = :aid
                """
            ),
            {"aid": aid},
        ).mappings().first()
        if not row:
            # Bootstrap from file once if present
            file_tok = _file_load()
            if file_tok:
                save_tokens(file_tok, aid=aid)
                return file_tok
            return None
        pg_tok = dict(row)
        # Optional local override (dev only). NEVER let a stale image file on
        # Railway overwrite a good Postgres refresh token — that burns the chain.
        allow_file = os.getenv("OAUTH_PREFER_TOKEN_FILE", "0") == "1"
        if allow_file:
            file_tok = _file_load()
            if file_tok and int(file_tok.get("expires_at") or 0) > int(
                pg_tok.get("expires_at") or 0
            ):
                save_tokens(file_tok, aid=aid)
                return file_tok
        return pg_tok


def save_tokens(tokens: Dict[str, Any], aid: Optional[str] = None) -> None:
    """
    Accept either raw OAuth response (expires_in) or stored shape (expires_at).
    """
    aid = aid or account_id()
    if "expires_at" in tokens:
        payload = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": int(tokens["expires_at"]),
            "scope": tokens.get("scope"),
            "token_type": tokens.get("token_type", "Bearer"),
        }
    else:
        payload = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": int(time.time()) + int(tokens.get("expires_in", 3600)),
            "scope": tokens.get("scope"),
            "token_type": tokens.get("token_type", "Bearer"),
        }

    # Always keep file mirror for local tooling / emergency
    _file_save(payload)

    if not use_postgres():
        return

    from db.pg import session_scope
    from db.schema import ensure_account

    ensure_account(aid)
    with session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO oauth_tokens
                    (account_id, access_token, refresh_token, expires_at, scope, token_type, updated_at)
                VALUES
                    (:aid, :access_token, :refresh_token, :expires_at, :scope, :token_type, now())
                ON CONFLICT (account_id) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = COALESCE(EXCLUDED.refresh_token, oauth_tokens.refresh_token),
                    expires_at = EXCLUDED.expires_at,
                    scope = EXCLUDED.scope,
                    token_type = EXCLUDED.token_type,
                    updated_at = now()
                """
            ),
            {
                "aid": aid,
                "access_token": payload["access_token"],
                "refresh_token": payload.get("refresh_token"),
                "expires_at": payload["expires_at"],
                "scope": payload.get("scope"),
                "token_type": payload.get("token_type") or "Bearer",
            },
        )
