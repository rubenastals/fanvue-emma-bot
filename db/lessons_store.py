"""Lessons store — Postgres or .lessons.json."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import text

from db import account_id, use_postgres

_ROOT = Path(__file__).resolve().parent.parent
_FILE = _ROOT / ".lessons.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _file_load() -> dict:
    if not _FILE.exists():
        return {"global_active": [], "global_pending": [], "per_fan": {}}
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"global_active": [], "global_pending": [], "per_fan": {}}


def _file_save(data: dict) -> None:
    tmp = str(_FILE) + ".tmp"
    Path(tmp).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, _FILE)


def load_bundle(aid: Optional[str] = None) -> dict:
    aid = aid or account_id()
    if not use_postgres():
        return _file_load()
    from db.pg import session_scope

    with session_scope() as session:
        active = session.execute(
            text(
                """
                SELECT text, source_fan, added_at
                FROM lessons_global
                WHERE account_id = :aid AND status = 'active'
                ORDER BY added_at ASC
                """
            ),
            {"aid": aid},
        ).mappings().all()
        pending = session.execute(
            text(
                """
                SELECT text, source_fan, added_at
                FROM lessons_global
                WHERE account_id = :aid AND status = 'pending'
                ORDER BY added_at ASC
                """
            ),
            {"aid": aid},
        ).mappings().all()
        fan_rows = session.execute(
            text(
                """
                SELECT fan_uuid, text, added_at FROM lessons_fan
                WHERE account_id = :aid ORDER BY added_at ASC
                """
            ),
            {"aid": aid},
        ).mappings().all()

    def _row(r):
        return {
            "text": r["text"],
            "added": r["added_at"].isoformat() if r["added_at"] else _now(),
            "source_fan": r.get("source_fan") or "",
        }

    per_fan: Dict[str, list] = {}
    for r in fan_rows:
        per_fan.setdefault(r["fan_uuid"], []).append(
            {
                "text": r["text"],
                "added": r["added_at"].isoformat() if r["added_at"] else _now(),
            }
        )
    return {
        "global_active": [_row(r) for r in active],
        "global_pending": [_row(r) for r in pending],
        "per_fan": per_fan,
    }


def save_bundle(data: dict, aid: Optional[str] = None) -> None:
    """Full replace (file mode or migrate)."""
    aid = aid or account_id()
    if not use_postgres():
        _file_save(data)
        return
    from db.pg import session_scope
    from db.schema import ensure_account

    ensure_account(aid)
    with session_scope() as session:
        session.execute(
            text("DELETE FROM lessons_global WHERE account_id = :aid"),
            {"aid": aid},
        )
        session.execute(
            text("DELETE FROM lessons_fan WHERE account_id = :aid"),
            {"aid": aid},
        )
        for status, key in (("active", "global_active"), ("pending", "global_pending")):
            for l in data.get(key) or []:
                session.execute(
                    text(
                        """
                        INSERT INTO lessons_global (account_id, status, text, source_fan, added_at)
                        VALUES (:aid, :status, :text, :source_fan, CAST(:added AS timestamptz))
                        """
                    ),
                    {
                        "aid": aid,
                        "status": status,
                        "text": l["text"],
                        "source_fan": l.get("source_fan") or "",
                        "added": l.get("added") or _now(),
                    },
                )
        for fid, lessons in (data.get("per_fan") or {}).items():
            for l in lessons:
                session.execute(
                    text(
                        """
                        INSERT INTO lessons_fan (account_id, fan_uuid, text, added_at)
                        VALUES (:aid, :fid, :text, CAST(:added AS timestamptz))
                        """
                    ),
                    {
                        "aid": aid,
                        "fid": fid,
                        "text": l["text"],
                        "added": l.get("added") or _now(),
                    },
                )
