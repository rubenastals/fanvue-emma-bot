"""Conversation event log — Postgres or JSONL files."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from db import account_id, use_postgres

_ROOT = Path(__file__).resolve().parent.parent
_DIR = _ROOT / "logs" / "conversations"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file(fan_uuid: str) -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in fan_uuid if c.isalnum() or c in "-_")
    return _DIR / f"{safe}.jsonl"


def append_event(
    fan_uuid: str,
    event_type: str,
    payload: Dict[str, Any],
    aid: Optional[str] = None,
) -> None:
    aid = aid or account_id()
    record = dict(payload)
    record["type"] = event_type
    record["ts"] = _now()

    # Always keep local JSONL mirror for debugging
    path = _file(fan_uuid)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if not use_postgres():
        return
    from db.pg import session_scope
    from db.schema import ensure_account

    ensure_account(aid)
    with session_scope() as session:
        session.execute(
            text(
                """
                INSERT INTO conversation_events (account_id, fan_uuid, event_type, payload, ts)
                VALUES (:aid, :fid, :etype, CAST(:payload AS jsonb), CAST(:ts AS timestamptz))
                """
            ),
            {
                "aid": aid,
                "fid": fan_uuid,
                "etype": event_type,
                "payload": json.dumps(record, ensure_ascii=False),
                "ts": record["ts"],
            },
        )


def read_recent(
    fan_uuid: str,
    *,
    max_records: int = 40,
    aid: Optional[str] = None,
) -> List[Dict[str, Any]]:
    aid = aid or account_id()
    if use_postgres():
        from db.pg import session_scope

        with session_scope() as session:
            rows = session.execute(
                text(
                    """
                    SELECT payload FROM conversation_events
                    WHERE account_id = :aid AND fan_uuid = :fid
                    ORDER BY ts DESC
                    LIMIT :lim
                    """
                ),
                {"aid": aid, "fid": fan_uuid, "lim": max_records},
            ).mappings().all()
        records = [dict(r["payload"]) for r in rows if r.get("payload")]
        records.reverse()
        if records:
            return records
        # fall through to file if PG empty (pre-migrate)

    path = _file(fan_uuid)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
    except OSError:
        return []
    records = []
    for line in lines[-max_records:]:
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def all_fan_uuids(aid: Optional[str] = None) -> List[str]:
    aid = aid or account_id()
    if use_postgres():
        from db.pg import session_scope

        with session_scope() as session:
            rows = session.execute(
                text(
                    """
                    SELECT DISTINCT fan_uuid FROM conversation_events
                    WHERE account_id = :aid
                    """
                ),
                {"aid": aid},
            ).all()
        uuids = [r[0] for r in rows]
        if uuids:
            return uuids
    if not _DIR.exists():
        return []
    return [p.stem for p in _DIR.glob("*.jsonl")]
