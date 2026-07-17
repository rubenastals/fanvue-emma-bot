"""Sync fanvue_media_map.json → Postgres vault_media (production catalog)."""
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

from db import account_id, use_postgres, vault_store
from db.schema import ensure_account, init_schema


def main() -> None:
    if not use_postgres():
        raise SystemExit("DATABASE_URL required")
    aid = account_id()
    init_schema(seed_account=True)
    ensure_account(aid)
    maps = sorted(
        (_ROOT / "exports").glob("vault_rank_*/fanvue_media_map.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    env_map = (os.getenv("FANVUE_MEDIA_MAP") or "").strip()
    map_path = Path(env_map) if env_map else (maps[0] if maps else None)
    if not map_path or not map_path.is_file():
        raise SystemExit("No fanvue_media_map.json found")
    raw = json.loads(map_path.read_text(encoding="utf-8"))
    n = vault_store.replace_items(
        raw.get("items") or [], aid=aid, catalog_version=map_path.parent.name
    )
    items = vault_store.load_items(aid=aid)
    by = {}
    for i in items:
        by[i["level"]] = by.get(i["level"], 0) + 1
    print(f"Synced {n} vault items for account={aid} from {map_path}")
    print("Levels:", dict(sorted(by.items())))


if __name__ == "__main__":
    main()
