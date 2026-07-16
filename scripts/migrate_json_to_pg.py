"""
Migrate local JSON/JSONL state into Postgres (+ Redis processed set).

Usage:
    # Start postgres/redis first (docker compose up -d postgres redis)
    set DATABASE_URL=postgresql://user:password@localhost:5432/fanvue_db
    set REDIS_URL=redis://localhost:6379/0
    set ACCOUNT_ID=emma
    python scripts/migrate_json_to_pg.py

Imports:
  - .fanvue_tokens.json → oauth_tokens
  - .fan_memory.json → fan_memory
  - .lessons.json → lessons_*
  - logs/conversations/*.jsonl → conversation_events
  - exports/.../fanvue_media_map.json → vault_media
  - .processed_messages.json → Redis processed set
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

from db import account_id, use_postgres, use_redis
from db.schema import ensure_account, init_schema
from db import (
    oauth_store,
    fan_memory_store,
    lessons_store,
    vault_store,
    processed_store,
    convo_store,
)


def main() -> None:
    if not use_postgres():
        raise SystemExit(
            "DATABASE_URL is required. Example:\n"
            "  postgresql://user:password@localhost:5432/fanvue_db"
        )

    aid = account_id()
    print(f"→ Migrating into account_id={aid}")
    init_schema(seed_account=True)
    ensure_account(aid, handle="im.emmacarter", persona_key="emma")

    # Tokens
    tok_path = _ROOT / ".fanvue_tokens.json"
    if tok_path.is_file():
        tokens = json.loads(tok_path.read_text(encoding="utf-8"))
        oauth_store.save_tokens(tokens, aid=aid)
        print(f"  ✓ oauth tokens from {tok_path.name}")
    else:
        print("  · no .fanvue_tokens.json (skip)")

    # Fan memory
    mem_path = _ROOT / ".fan_memory.json"
    if mem_path.is_file():
        data = json.loads(mem_path.read_text(encoding="utf-8"))
        fan_memory_store.save_all(data, aid=aid)
        print(f"  ✓ fan_memory: {len(data)} fan(s)")
    else:
        print("  · no .fan_memory.json (skip)")

    # Lessons
    les_path = _ROOT / ".lessons.json"
    if les_path.is_file():
        lessons = json.loads(les_path.read_text(encoding="utf-8"))
        lessons_store.save_bundle(lessons, aid=aid)
        n_a = len(lessons.get("global_active") or [])
        n_p = len(lessons.get("global_pending") or [])
        n_f = sum(len(v) for v in (lessons.get("per_fan") or {}).values())
        print(f"  ✓ lessons: active={n_a} pending={n_p} fan={n_f}")
    else:
        print("  · no .lessons.json (skip)")

    # Vault map
    maps = sorted(
        (_ROOT / "exports").glob("vault_rank_*/fanvue_media_map.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    env_map = (os.getenv("FANVUE_MEDIA_MAP") or "").strip()
    map_path = Path(env_map) if env_map else (maps[0] if maps else None)
    if map_path and map_path.is_file():
        raw = json.loads(map_path.read_text(encoding="utf-8"))
        items = raw.get("items") or []
        n = vault_store.replace_items(
            items, aid=aid, catalog_version=map_path.parent.name
        )
        print(f"  ✓ vault_media: {n} items from {map_path}")
    else:
        print("  · no fanvue_media_map.json (skip)")

    # Conversation JSONL
    convo_dir = _ROOT / "logs" / "conversations"
    n_ev = 0
    if convo_dir.is_dir():
        for path in convo_dir.glob("*.jsonl"):
            fan_uuid = path.stem
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                etype = rec.get("type") or "turn"
                ts = rec.get("ts")
                from db.pg import session_scope
                from sqlalchemy import text

                with session_scope() as session:
                    if ts:
                        session.execute(
                            text(
                                """
                                INSERT INTO conversation_events
                                    (account_id, fan_uuid, event_type, payload, ts)
                                VALUES
                                    (:aid, :fid, :etype, CAST(:payload AS jsonb),
                                     CAST(:ts AS timestamptz))
                                """
                            ),
                            {
                                "aid": aid,
                                "fid": fan_uuid,
                                "etype": etype,
                                "payload": json.dumps(rec, ensure_ascii=False),
                                "ts": ts,
                            },
                        )
                    else:
                        session.execute(
                            text(
                                """
                                INSERT INTO conversation_events
                                    (account_id, fan_uuid, event_type, payload)
                                VALUES
                                    (:aid, :fid, :etype, CAST(:payload AS jsonb))
                                """
                            ),
                            {
                                "aid": aid,
                                "fid": fan_uuid,
                                "etype": etype,
                                "payload": json.dumps(rec, ensure_ascii=False),
                            },
                        )
                n_ev += 1
        print(f"  ✓ conversation_events: {n_ev}")
    else:
        print("  · no logs/conversations (skip)")

    # Processed → Redis
    proc_path = _ROOT / ".processed_messages.json"
    if proc_path.is_file() and use_redis():
        uuids = set(json.loads(proc_path.read_text(encoding="utf-8")))
        processed_store.save(uuids, aid=aid)
        print(f"  ✓ processed messages → Redis: {len(uuids)}")
    elif proc_path.is_file():
        print("  · REDIS_URL not set — processed left in JSON file")
    else:
        print("  · no .processed_messages.json (skip)")

    print("\n✅ Migration complete. Start poller with DATABASE_URL (+ REDIS_URL) set.")


if __name__ == "__main__":
    main()
