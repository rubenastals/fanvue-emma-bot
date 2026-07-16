"""
Postgres + Redis persistence for the poller path (multi-account ready).

If DATABASE_URL is unset → file/JSON fallback (local dev).
If DATABASE_URL is set → Postgres is canonical; Redis for processed + locks.
"""
from __future__ import annotations

import os
from typing import Optional

DEFAULT_ACCOUNT_ID = "emma"


def account_id() -> str:
    return (os.getenv("ACCOUNT_ID") or DEFAULT_ACCOUNT_ID).strip() or DEFAULT_ACCOUNT_ID


def database_url() -> Optional[str]:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return None
    # Railway sometimes gives postgres:// — SQLAlchemy wants postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def redis_url() -> str:
    return (os.getenv("REDIS_URL") or "redis://localhost:6379/0").strip()


def use_postgres() -> bool:
    return bool(database_url())


def use_redis() -> bool:
    """Redis required when Postgres is on; optional otherwise."""
    if use_postgres():
        return True
    return bool((os.getenv("REDIS_URL") or "").strip())
