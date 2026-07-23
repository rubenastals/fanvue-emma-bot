"""Purge test/junk fan_memory rows from Postgres (per account).

Usage:
    ACCOUNT_ID=emma python scripts/purge_junk_fan_memory.py --dry-run
    ACCOUNT_ID=emma python scripts/purge_junk_fan_memory.py
"""
from __future__ import annotations

import argparse
import os
import re
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def _is_junk(fan_uuid: str, handle: str, data: dict) -> bool:
    from core import fan_memory

    mem = data or {}
    msgs = int(mem.get("messages") or 0)
    h = (handle or mem.get("handle") or "").strip()
    if mem.get("_deleted"):
        return True
    if fan_uuid.startswith("test-") or fan_uuid.startswith("test_"):
        return True
    if fan_memory.is_junk_fan_handle(h):
        return True
    if msgs > 0 and _UUID.match(fan_uuid):
        return False
    if h and _UUID.match(fan_uuid):
        return False
    if not h and (not _UUID.match(fan_uuid) or fan_uuid.count("-") < 4):
        return True
    if msgs == 0 and not h:
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="", help="emma|sophia (default ACCOUNT_ID)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.account:
        os.environ["ACCOUNT_ID"] = args.account.strip().lower()

    from db import account_id, use_postgres
    from sqlalchemy import text
    from db.pg import session_scope

    aid = account_id()
    if not use_postgres():
        print("❌ Postgres required")
        sys.exit(1)

    with session_scope() as s:
        rows = s.execute(
            text(
                "SELECT fan_uuid, handle, data FROM fan_memory WHERE account_id = :aid"
            ),
            {"aid": aid},
        ).mappings().all()

    keep, delete = [], []
    for r in rows:
        fid = r["fan_uuid"]
        data = dict(r["data"] or {})
        handle = r["handle"] or ""
        item = (fid, handle or data.get("handle") or "", int(data.get("messages") or 0))
        if _is_junk(fid, handle, data):
            delete.append(item)
        else:
            keep.append(item)

    print(f"account={aid} total={len(rows)} keep={len(keep)} delete={len(delete)}")
    print("\n--- keep ---")
    for fid, h, m in sorted(keep, key=lambda x: -x[2]):
        print(f"  @{h or '?'} ({fid[:8]}…) msgs={m}")

    if args.dry_run:
        print(f"\n(dry-run — would delete {len(delete)} rows)")
        return

    if not delete:
        print("\n✅ nothing to delete")
        return

    ids = [d[0] for d in delete]
    with session_scope() as s:
        s.execute(
            text(
                "DELETE FROM fan_memory WHERE account_id = :aid AND fan_uuid = ANY(:ids)"
            ),
            {"aid": aid, "ids": ids},
        )
    print(f"\n✅ deleted {len(delete)} junk rows — {len(keep)} fans remain")


if __name__ == "__main__":
    main()
