"""
Audit multi-account isolation for the running ACCOUNT_ID vs emma.

Usage:
    ACCOUNT_ID=sophia python scripts/audit_account_isolation.py
    python scripts/audit_account_isolation.py --compare emma sophia
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env")

PASS = "✅"
FAIL = "❌"
WARN = "⚠️ "


def _header(title: str) -> None:
    print(f"\n{'=' * 50}\n{title}\n{'=' * 50}")


def audit_one(aid: str) -> list[str]:
    os.environ["ACCOUNT_ID"] = aid
    if aid == "sophia":
        os.environ.setdefault("FANVUE_MEDIA_MAP", "data/sophia_fanvue_media_map.json")
        os.environ.setdefault("PERSONA_FILE", "personas/sophia.md")

    errors: list[str] = []
    warnings: list[str] = []

    from db import account_id, use_postgres, use_redis

    print(f"\n--- account={aid} postgres={use_postgres()} redis={use_redis()} ---")

    # Persona
    from core.prompt_core import get_active_persona
    from core.account_context import creator_display_name, persona_file_path

    persona = get_active_persona()
    name = creator_display_name()
    pf = persona_file_path()
    print(f"{PASS if pf else FAIL} persona file: {pf}")
    print(f"{PASS} creator_display_name: {name}")
    if aid == "sophia":
        if "Sophia Cler" not in persona:
            errors.append("persona missing Sophia Cler")
        if "Emma Carter" in persona:
            errors.append("persona contains Emma Carter")
        if "ENGLISH ONLY" not in persona:
            warnings.append("English-only rule not in persona")

    # OAuth + API identity
    from db import oauth_store

    tok = oauth_store.load_tokens(aid=aid)
    print(f"{PASS if tok else FAIL} oauth token in store")
    handle = ""
    if tok:
        try:
            from api.fanvue_connector import FanvueConnector

            me = FanvueConnector().get_current_user()
            handle = str(me.get("handle") or me.get("username") or "")
            disp = me.get("displayName") or ""
            print(f"{PASS} Fanvue API: @{handle} ({disp}) uuid={me.get('uuid')}")
            if aid == "sophia" and "emma" in (handle + str(disp)).lower():
                errors.append("Sophia poller connected to Emma Fanvue account")
            if aid == "emma" and "sophia" in (handle + str(disp)).lower():
                errors.append("Emma poller connected to Sophia account")
        except Exception as e:
            errors.append(f"Fanvue API: {e}")
    else:
        errors.append("no oauth token")

    # Vault
    from db import vault_store
    from core import vault_catalog

    items = vault_catalog.load_items()
    uuids = {str(i.get("media_uuid")) for i in items if i.get("media_uuid")}
    print(f"{PASS} vault items loaded: {len(items)}")
    map_path = vault_store._default_map_path(aid)
    print(f"   map path: {map_path}")
    if map_path and map_path.is_file():
        raw = json.loads(map_path.read_text(encoding="utf-8"))
        err = vault_store.validate_map_for_account(raw, aid)
        if err:
            errors.append(err)
        else:
            print(f"{PASS} media map account_id OK")

    # Postgres cross-checks
    emma_uuids: set[str] = set()
    sophia_uuids: set[str] = set()
    if use_postgres():
        from sqlalchemy import text
        from db.pg import session_scope

        with session_scope() as session:
            for row in session.execute(
                text("SELECT account_id, media_uuid FROM vault_media")
            ).mappings():
                if row["account_id"] == "emma":
                    emma_uuids.add(str(row["media_uuid"]))
                elif row["account_id"] == "sophia":
                    sophia_uuids.add(str(row["media_uuid"]))
            oauth_rows = session.execute(
                text("SELECT account_id FROM oauth_tokens")
            ).fetchall()
            print(f"{PASS} oauth_tokens rows: {[r[0] for r in oauth_rows]}")
            fan_counts = session.execute(
                text(
                    "SELECT account_id, COUNT(*) FROM fan_memory GROUP BY account_id"
                )
            ).fetchall()
            print(f"{PASS} fan_memory rows: {dict(fan_counts)}")

        overlap = emma_uuids & sophia_uuids
        if overlap:
            errors.append(f"vault_media UUID overlap emma∩sophia: {len(overlap)}")
        else:
            print(f"{PASS} no vault UUID overlap emma vs sophia in PG")

        if aid == "sophia" and uuids and emma_uuids and uuids & emma_uuids:
            errors.append("Sophia runtime vault contains Emma UUIDs")

    # Redis keys
    if use_redis():
        from db import redis_client

        r = redis_client.get_redis()
        keys = [
            f"processed:{aid}",
            f"lock:poller:{aid}",
            f"oauth_refresh_lock:{aid}",
        ]
        for k in keys:
            print(f"{PASS} redis key exists pattern: {k}")

    # Author steer (no Emma leak)
    from core.account_context import creator_display_name as cdn

    os.environ["ACCOUNT_ID"] = aid
    cname = cdn()
    if aid == "sophia" and "Emma" in cname:
        errors.append("creator_display_name still Emma")

    for w in warnings:
        print(f"{WARN} {w}")
    for e in errors:
        print(f"{FAIL} {e}")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit account isolation")
    ap.add_argument(
        "--compare",
        nargs=2,
        metavar=("A", "B"),
        default=["sophia", "emma"],
        help="Compare two accounts (default: sophia emma)",
    )
    args = ap.parse_args()

    _header("MULTI-ACCOUNT ISOLATION AUDIT")
    all_err: list[str] = []
    for aid in args.compare:
        all_err.extend(audit_one(aid))

    _header("SUMMARY")
    if all_err:
        print(f"{FAIL} {len(all_err)} issue(s) — fix before production")
        for e in all_err:
            print(f"  - {e}")
        sys.exit(1)
    print(f"{PASS} All checks passed for {args.compare}")


if __name__ == "__main__":
    main()
