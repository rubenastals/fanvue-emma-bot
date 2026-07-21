"""Create poller-path tables + seed account emma."""
from __future__ import annotations

from sqlalchemy import text

from db import account_id
import os
from db.pg import get_engine, session_scope

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    handle TEXT,
    creator_uuid TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    persona_key TEXT DEFAULT 'emma',
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    account_id TEXT PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    access_token TEXT NOT NULL,
    refresh_token TEXT,
    expires_at BIGINT NOT NULL,
    scope TEXT,
    token_type TEXT DEFAULT 'Bearer',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS fan_memory (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    fan_uuid TEXT NOT NULL,
    handle TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (account_id, fan_uuid)
);

CREATE TABLE IF NOT EXISTS lessons_global (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('active', 'pending')),
    text TEXT NOT NULL,
    source_fan TEXT,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lessons_global_acct_status
    ON lessons_global (account_id, status);

CREATE TABLE IF NOT EXISTS lessons_fan (
    id SERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    fan_uuid TEXT NOT NULL,
    text TEXT NOT NULL,
    added_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_lessons_fan_acct
    ON lessons_fan (account_id, fan_uuid);

CREATE TABLE IF NOT EXISTS conversation_events (
    id BIGSERIAL PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    fan_uuid TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_convo_events_fan_ts
    ON conversation_events (account_id, fan_uuid, ts DESC);

CREATE TABLE IF NOT EXISTS vault_media (
    account_id TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    media_uuid TEXT NOT NULL,
    file_name TEXT,
    level INT,
    score INT,
    price NUMERIC(10, 2),
    folder TEXT,
    label TEXT,
    catalog_version TEXT,
    PRIMARY KEY (account_id, media_uuid)
);
"""


def init_schema(*, seed_account: bool = True) -> None:
    engine = get_engine()
    with engine.begin() as conn:
        for stmt in SCHEMA_SQL.split(";"):
            s = stmt.strip()
            if s:
                conn.execute(text(s))
    if seed_account:
        handle = os.getenv("FANVUE_CREATOR_HANDLE", "im.emmacarter")
        persona_key = os.getenv("PERSONA_KEY", account_id())
        ensure_account(account_id(), handle=handle, persona_key=persona_key)


def ensure_account(
    aid: str,
    *,
    handle: str = "",
    creator_uuid: str = "",
    persona_key: str = "emma",
) -> None:
    with session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO accounts (id, handle, creator_uuid, persona_key, active)
                VALUES (:id, :handle, :creator_uuid, :persona_key, TRUE)
                ON CONFLICT (id) DO UPDATE SET
                    handle = COALESCE(NULLIF(:handle, ''), accounts.handle),
                    creator_uuid = COALESCE(NULLIF(:creator_uuid, ''), accounts.creator_uuid),
                    persona_key = COALESCE(NULLIF(:persona_key, ''), accounts.persona_key),
                    updated_at = now()
                """
            ),
            {
                "id": aid,
                "handle": handle or None,
                "creator_uuid": creator_uuid or None,
                "persona_key": persona_key,
            },
        )


if __name__ == "__main__":
    init_schema()
    print("OK: schema ready, account seeded:", account_id())
