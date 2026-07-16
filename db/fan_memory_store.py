"""Fan memory — JSONB per (account_id, fan_uuid) or .fan_memory.json fallback."""
from __future__ import annotations

import json
import os
from typing import Dict, Optional

from sqlalchemy import text

from db import account_id, use_postgres

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FILE = os.path.join(_ROOT, ".fan_memory.json")


def _file_load_all() -> Dict[str, dict]:
    if not os.path.exists(_FILE):
        return {}
    try:
        with open(_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _file_save_all(data: Dict[str, dict]) -> None:
    tmp = _FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _FILE)


def get_fan(fan_uuid: str, aid: Optional[str] = None) -> dict:
    aid = aid or account_id()
    if not use_postgres():
        return _file_load_all().get(fan_uuid, {})
    from db.pg import session_scope

    with session_scope() as session:
        row = session.execute(
            text(
                """
                SELECT data FROM fan_memory
                WHERE account_id = :aid AND fan_uuid = :fid
                """
            ),
            {"aid": aid, "fid": fan_uuid},
        ).mappings().first()
        if not row:
            return {}
        data = row["data"]
        return dict(data) if data else {}


def set_fan(fan_uuid: str, mem: dict, aid: Optional[str] = None) -> None:
    aid = aid or account_id()
    if not use_postgres():
        data = _file_load_all()
        data[fan_uuid] = mem
        _file_save_all(data)
        return
    from db.pg import session_scope
    from db.schema import ensure_account

    ensure_account(aid)
    handle = (mem or {}).get("handle") or ""
    with session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO fan_memory (account_id, fan_uuid, handle, data, updated_at)
                VALUES (:aid, :fid, :handle, CAST(:data AS jsonb), now())
                ON CONFLICT (account_id, fan_uuid) DO UPDATE SET
                    handle = EXCLUDED.handle,
                    data = EXCLUDED.data,
                    updated_at = now()
                """
            ),
            {
                "aid": aid,
                "fid": fan_uuid,
                "handle": handle,
                "data": json.dumps(mem, ensure_ascii=False),
            },
        )


def load_all(aid: Optional[str] = None) -> Dict[str, dict]:
    aid = aid or account_id()
    if not use_postgres():
        return _file_load_all()
    from db.pg import session_scope

    with session_scope() as session:
        rows = session.execute(
            text("SELECT fan_uuid, data FROM fan_memory WHERE account_id = :aid"),
            {"aid": aid},
        ).mappings().all()
        out: Dict[str, dict] = {}
        for r in rows:
            data = r["data"]
            out[r["fan_uuid"]] = dict(data) if data else {}
        return out


def save_all(data: Dict[str, dict], aid: Optional[str] = None) -> None:
    """Replace all fans for account (migrate / rare bulk)."""
    aid = aid or account_id()
    if not use_postgres():
        _file_save_all(data)
        return
    from db.pg import session_scope
    from db.schema import ensure_account

    ensure_account(aid)
    with session_scope() as session:
        session.execute(
            text("DELETE FROM fan_memory WHERE account_id = :aid"),
            {"aid": aid},
        )
        for fid, mem in data.items():
            session.execute(
                text(
                    """
                    INSERT INTO fan_memory (account_id, fan_uuid, handle, data, updated_at)
                    VALUES (:aid, :fid, :handle, CAST(:data AS jsonb), now())
                    """
                ),
                {
                    "aid": aid,
                    "fid": fid,
                    "handle": (mem or {}).get("handle") or "",
                    "data": json.dumps(mem, ensure_ascii=False),
                },
            )
