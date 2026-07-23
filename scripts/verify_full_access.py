"""
Full access check — Emma + Sophia (same infra as production).

Usage:
    python scripts/verify_full_access.py
    python scripts/verify_full_access.py --account sophia
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

OK = "✅"
FAIL = "❌"
WARN = "⚠️ "


def _check_env(aid: str) -> list[str]:
    errors: list[str] = []
    required = [
        "FANVUE_CLIENT_ID",
        "FANVUE_CLIENT_SECRET",
        "DEEPSEEK_API_KEY",
    ]
    for k in required:
        if not (os.getenv(k) or "").strip():
            errors.append(f"missing env {k}")

    if not (os.getenv("DATABASE_URL") or "").strip():
        errors.append("missing DATABASE_URL (file-mode only — not production parity)")
    if not (os.getenv("REDIS_URL") or "").strip():
        errors.append("missing REDIS_URL")

    if aid == "sophia":
        if not os.path.isfile(_ROOT / "personas" / "sophia.md"):
            errors.append("missing personas/sophia.md")
        map_path = os.getenv("FANVUE_MEDIA_MAP") or "data/sophia_fanvue_media_map.json"
        if not os.path.isfile(_ROOT / map_path if not map_path.startswith("/") else map_path):
            errors.append(f"missing vault map {map_path}")
    return errors


def _audit_account(aid: str) -> list[str]:
    os.environ["ACCOUNT_ID"] = aid
    if aid == "sophia":
        os.environ.setdefault("FANVUE_MEDIA_MAP", "data/sophia_fanvue_media_map.json")
        os.environ.setdefault("PERSONA_FILE", "personas/sophia.md")

    errors: list[str] = []
    from db import account_id, use_postgres, use_redis

    print(f"\n{'='*50}\nACCOUNT: {aid}\n{'='*50}")
    print(f"postgres={use_postgres()} redis={use_redis()} account_id={account_id()}")

    errors.extend(_check_env(aid))

    # Persona
    from core.prompt_core import get_active_persona
    from core.account_context import creator_display_name

    persona = get_active_persona()
    name = creator_display_name()
    print(f"{OK} persona: {name} ({len(persona)} chars)")

    # OAuth + Fanvue
    from db import oauth_store

    tok = oauth_store.load_tokens(aid=aid)
    if not tok:
        errors.append(f"no oauth token for {aid}")
        print(f"{FAIL} oauth token")
        return errors

    print(f"{OK} oauth token present")
    try:
        from api.fanvue_connector import FanvueConnector

        me = FanvueConnector().get_current_user()
        handle = me.get("handle") or me.get("username")
        disp = me.get("displayName") or ""
        print(f"{OK} Fanvue API: @{handle} ({disp}) uuid={me.get('uuid')}")
        blob = (str(handle) + disp).lower()
        if aid == "sophia" and "emma" in blob and "sophia" not in blob:
            errors.append("sophia account_id but Emma Fanvue handle")
        if aid == "emma" and "sophia" in blob and "emma" not in blob:
            errors.append("emma account_id but Sophia handle")
    except Exception as e:
        errors.append(f"Fanvue API: {e}")
        print(f"{FAIL} Fanvue API: {e}")

    # Vault
    from core import vault_catalog

    items = vault_catalog.load_items()
    print(f"{OK} vault items: {len(items)} (0 OK for bonding-only)")

    # PG rows
    if use_postgres():
        from sqlalchemy import text
        from db.pg import session_scope

        with session_scope() as session:
            row = session.execute(
                text("SELECT handle, persona_key, active FROM accounts WHERE id = :aid"),
                {"aid": aid},
            ).mappings().first()
            if row:
                print(f"{OK} accounts row: {dict(row)}")
            else:
                errors.append(f"no accounts row for {aid}")
            oauth = session.execute(
                text(
                    "SELECT account_id, expires_at FROM oauth_tokens WHERE account_id = :aid"
                ),
                {"aid": aid},
            ).mappings().first()
            if oauth:
                print(f"{OK} oauth_tokens row expires_at={oauth['expires_at']}")
            fans = session.execute(
                text("SELECT COUNT(*) FROM fan_memory WHERE account_id = :aid"),
                {"aid": aid},
            ).scalar()
            vault = session.execute(
                text("SELECT COUNT(*) FROM vault_media WHERE account_id = :aid"),
                {"aid": aid},
            ).scalar()
            print(f"{OK} fan_memory rows: {fans} | vault_media rows: {vault}")

    # Banned stamp fix present
    from core.reply_sanitize import is_banned_reply_stamp, coerce_sendable_reply

    bad = "Hey... look at me when I'm talking to you."
    fixed = coerce_sendable_reply(bad, want_spanish=False, history_turns=[])
    if is_banned_reply_stamp(fixed):
        errors.append("birbo stamp fix not working")
    else:
        print(f"{OK} birbo stamp blocked → {fixed[:50]}…")

    return errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="", help="sophia or emma only (default: both)")
    args = ap.parse_args()

    accounts = [args.account] if args.account else ["emma", "sophia"]
    all_err: list[str] = []
    for aid in accounts:
        all_err.extend(_audit_account(aid.strip().lower()))

    print(f"\n{'='*50}\nSUMMARY\n{'='*50}")
    if all_err:
        for e in all_err:
            print(f"{FAIL} {e}")
        sys.exit(1)
    print(f"{OK} Full access OK for: {', '.join(accounts)}")


if __name__ == "__main__":
    main()
