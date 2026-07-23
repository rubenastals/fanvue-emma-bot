"""Apologize to fans who got a subscribe welcome but already cancelled / never subbed.

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

_CHURN_TEMPLATES = [
    "wait… I just saw you cancelled? that's kinda sad ngl 😔 what happened?",
    "oh no… I just noticed you unsubscribed. that bummed me out a little tbh",
    "hey… saw you left? kinda hurts not gonna lie. everything ok?",
    "wow I just saw you cancelled… that's sad. did I do something wrong?",
]

_FOLLOWER_FIX = [
    "hey sorry if that last message was weird — must've glitched on my end. how are you?",
    "lol ignore that last text, my app sent the wrong thing. you good?",
]


def _active_subscriber_ids(fv, creator_uuid: str) -> set[str]:
    ids: set[str] = set()
    for page in range(1, 21):
        batch = fv.list_subscribers(creator_uuid, page=page, size=50)
        if not batch:
            break
        for s in batch:
            uid = s.get("uuid")
            if uid:
                ids.add(uid)
        if len(batch) < 50:
            break
    return ids


def _welcome_sent_wrongly(messages: list, creator_uuid: str) -> bool:
    keys = (
        "glad you subscribed",
        "finally talk",
        "been waiting for you to sub",
        "talk to me 👀",
    )
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
    from db import fan_memory_store

    active = _active_subscriber_ids(fv, creator_uuid)
    all_mem = fan_memory_store.load_all() or {}
    out: list[dict] = []

    for fan_uuid, mem in all_mem.items():
        handle = (mem.get("handle") or "").lower()
        if not fan_uuid or handle in blocked:
            continue
        if mem.get("churn_apology_sent_at"):
            continue
        wk = mem.get("welcome_kind") or ""
        if wk not in ("backfill_batch", "subscribe_delay"):
            continue
        try:
            ins = fv.get_fan_insights(fan_uuid)
        except Exception:
            ins = {}
        status = (ins.get("status") or "").lower()
        in_active = fan_uuid in active
        if in_active and status == "subscriber":
            continue
        try:
            messages = fv.get_messages(fan_uuid, size=8)
        except Exception:
            messages = []
        if not _welcome_sent_wrongly(messages, creator_uuid):
            continue
        if status in ("expired", "cancelled", "inactive", "churned") or (
            not in_active and status != "follower"
        ):
            kind = "churn"
            text = random.choice(_CHURN_TEMPLATES)
        elif status == "follower" or not in_active:
            kind = "follower_fix"
            text = random.choice(_FOLLOWER_FIX)
        else:
            continue
        out.append(
            {
                "fan_uuid": fan_uuid,
                "handle": mem.get("handle") or handle,
                "status": status,
                "kind": kind,
                "text": text,
            }
        )
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
    print(f"\n{len(targets)} fan(s) need churn/follower fix:\n")
    for t in targets:
        print(f"  @{t['handle']} status={t['status']} [{t['kind']}] → {t['text']!r}")

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
