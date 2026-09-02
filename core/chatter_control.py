"""Global / per-account chatter pause (Redis + env)."""
from __future__ import annotations

import os
from typing import Optional

_GLOBAL_KEY = "chatter:paused:global"


def _redis():
    try:
        from db import redis_client, use_redis

        if use_redis():
            return redis_client.get_redis()
    except Exception:
        return None
    return None


def _account_key(aid: str) -> str:
    return f"chatter:paused:{aid}"


def chatter_enabled_env() -> bool:
    return os.getenv("CHATTER_ENABLED", "1") == "1"


def is_account_active(aid: str) -> bool:
    """Postgres accounts.active; True when DB unavailable (dev file mode)."""
    try:
        from db import use_postgres

        if not use_postgres():
            return True
        from sqlalchemy import text

        from db.pg import session_scope

        with session_scope() as session:
            row = session.execute(
                text("SELECT active FROM accounts WHERE id = :aid"),
                {"aid": aid},
            ).scalar()
        return True if row is None else bool(row)
    except Exception:
        return True


def is_chatter_paused(aid: Optional[str] = None) -> bool:
    """True when env, DB inactive, Redis global, or per-account pause is active."""
    if not chatter_enabled_env():
        return True
    if aid and not is_account_active(aid):
        return True
    r = _redis()
    if r is None:
        return False
    try:
        if r.exists(_GLOBAL_KEY):
            return True
        if aid and r.exists(_account_key(aid)):
            return True
    except Exception:
        return False
    return False


def pause_chatter(
    *,
    account_id: Optional[str] = None,
    global_pause: bool = False,
    reason: str = "",
) -> None:
    r = _redis()
    if r is None:
        raise RuntimeError("Redis unavailable — cannot set chatter pause")
    note = (reason or "manual")[:200]
    if global_pause:
        r.set(_GLOBAL_KEY, note)
    if account_id:
        r.set(_account_key(account_id), note)


def resume_chatter(*, account_id: Optional[str] = None, global_pause: bool = False) -> None:
    r = _redis()
    if r is None:
        raise RuntimeError("Redis unavailable — cannot clear chatter pause")
    if global_pause:
        r.delete(_GLOBAL_KEY)
    if account_id:
        r.delete(_account_key(account_id))


def list_paused_accounts() -> dict:
    """Return {global: reason|None, accounts: {aid: reason}}."""
    out: dict = {"global": None, "accounts": {}}
    r = _redis()
    if r is None:
        return out
    try:
        g = r.get(_GLOBAL_KEY)
        if g:
            out["global"] = g
        for key in r.scan_iter("chatter:paused:*"):
            if key == _GLOBAL_KEY:
                continue
            aid = key.split(":", 2)[-1]
            out["accounts"][aid] = r.get(key) or ""
    except Exception:
        pass
    return out
