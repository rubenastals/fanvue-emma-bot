"""Apologize to expired fans who got a subscribe welcome by mistake.

Prefer `scripts/onboard_new_account.py` on new account connect.

Usage:
    ACCOUNT_ID=sophia python scripts/churn_welcome_fix.py --dry-run
    ACCOUNT_ID=sophia python scripts/churn_welcome_fix.py
"""
from __future__ import annotations

import argparse
import os
import random
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from core.welcome import welcome_message_sent

_CHURN_TEMPLATES = [
    "wait… I just saw you cancelled? that's kinda sad ngl 😔 what happened?",
    "oh no… I just noticed you unsubscribed. that bummed me out a little tbh",
    "hey… saw you left? kinda hurts not gonna lie. everything ok?",
    "wow I just saw you cancelled… that's sad. did I do something wrong?",
]


def _churn_already_sent(messages: list, creator_uuid: str) -> bool:
    keys = ("cancelled", "unsubscribed", "left?", "saw you", "bummed me out")
    for m in messages or []:
        sender = m.get("sender") or {}
        sid = sender.get("uuid") if isinstance(sender, dict) else None
        if sid != creator_uuid:
            continue
        text = (m.get("text") or "").lower()
        if any(k in text for k in keys):
            return True
    return False


def _collect_targets(fv, creator_uuid: str, blocked: set[str]) -> list[dict]:
    from core.account_onboard import active_subscriber_ids, list_all_chats
    from db import fan_memory_store

    active = active_subscriber_ids(fv, creator_uuid)
    all_mem = fan_memory_store.load_all() or {}
    out: list[dict] = []
    seen: set[str] = set()

    def _maybe_add(fan_uuid: str, handle: str):
        handle_l = (handle or "").lower()
        if not fan_uuid or handle_l in blocked or fan_uuid in seen:
            return
        mem = all_mem.get(fan_uuid) or {}
        if mem.get("churn_apology_sent_at"):
            return
        try:
            ins = fv.get_fan_insights(fan_uuid)
        except Exception:
            ins = {}
        status = (ins.get("status") or "").lower()
        in_active = fan_uuid in active
        if in_active and status == "subscriber":
            return
        if status == "follower":
            return
        try:
            messages = fv.get_messages(fan_uuid, size=8)
        except Exception:
            messages = []
        if not welcome_message_sent(messages, creator_uuid):
            return
        if _churn_already_sent(messages, creator_uuid):
            return
        if status not in ("expired", "cancelled", "inactive", "churned") and in_active:
            return
        seen.add(fan_uuid)
        out.append(
            {
                "fan_uuid": fan_uuid,
                "handle": handle or handle_l,
                "status": status,
                "kind": "churn",
                "text": random.choice(_CHURN_TEMPLATES),
            }
        )

    for fan_uuid, mem in all_mem.items():
        _maybe_add(fan_uuid, mem.get("handle") or "")

    for chat in list_all_chats(fv):
        user = chat.get("user") or {}
        _maybe_add(user.get("uuid"), user.get("handle") or "")

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay", type=float, default=5.0)
    args = ap.parse_args()

    if args.account:
        os.environ["ACCOUNT_ID"] = args.account.strip().lower()

    from datetime import datetime, timezone

    from config import config
    from api.fanvue_connector import FanvueConnector
    from core import fan_memory
    from db import account_id

    blocked = {
        h.strip().lower()
        for h in (getattr(config, "BLOCKED_HANDLES", []) or [])
        if h.strip()
    }

    fv = FanvueConnector()
    me = fv.get_current_user()
    creator_uuid = me.get("uuid")
    print(f"account={account_id()} creator=@{me.get('handle')}")

    targets = _collect_targets(fv, creator_uuid, blocked)
    print(f"\n{len(targets)} fan(s) need churn apology:\n")
    for t in targets:
        print(f"  @{t['handle']} status={t['status']} → {t['text']!r}")

    if args.dry_run:
        print("\n(dry-run)")
        return
    if not targets:
        print("\n✅ nothing to send")
        return

    sent = 0
    for t in targets:
        try:
            fv.ensure_chat(creator_uuid, t["fan_uuid"])
            time.sleep(1.5)
            fv.send_message(t["fan_uuid"], t["text"])
            fan_memory.patch_fanvue_platform(
                t["fan_uuid"],
                {
                    "churn_apology_sent_at": datetime.now(timezone.utc).isoformat(),
                    "churn_apology_kind": t["kind"],
                },
                fan_handle=t["handle"],
            )
            sent += 1
            print(f"   💬 sent @{t['handle']}: {t['text']}")
        except Exception as exc:
            print(f"   ❌ @{t['handle']}: {exc}")
        time.sleep(max(2.0, args.delay))

    print(f"\n✅ sent {sent}/{len(targets)}")


if __name__ == "__main__":
    main()
