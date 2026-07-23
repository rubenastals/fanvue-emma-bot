"""Backfill welcome DMs for subscribers who never opened chat.

Usage:
    ACCOUNT_ID=sophia python scripts/welcome_unopened_subs.py --dry-run
    ACCOUNT_ID=sophia python scripts/welcome_unopened_subs.py
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))


def _collect_candidates(fv, creator_uuid: str, blocked: set[str]) -> list[dict]:
    from core import fan_memory
    from core.welcome import (
        _already_welcomed_by_us,
        _fan_has_real_chat,
        pick_welcome_text,
    )

    all_subs: list[dict] = []
    for page in range(1, 21):
        batch = fv.list_subscribers(creator_uuid, page=page, size=50)
        if not batch:
            break
        all_subs.extend(batch)
        if len(batch) < 50:
            break

    out: list[dict] = []
    for sub in all_subs:
        fan_uuid = sub.get("uuid")
        handle = (sub.get("handle") or "fan").lower()
        if not fan_uuid or fan_uuid == creator_uuid:
            continue
        if handle in blocked:
            continue
        mem = fan_memory.get(fan_uuid) or {}
        if int(mem.get("messages") or 0) > 0:
            continue
        try:
            messages = fv.get_messages(fan_uuid, size=10)
        except Exception:
            messages = []
        if _fan_has_real_chat(messages, fan_uuid):
            continue
        if _already_welcomed_by_us(messages, creator_uuid):
            continue
        out.append(
            {
                "fan_uuid": fan_uuid,
                "handle": sub.get("handle") or handle,
                "firstSubscribedAt": sub.get("firstSubscribedAt"),
                "text": pick_welcome_text(spanish=False),
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="", help="emma|sophia")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay", type=float, default=4.0, help="Seconds between sends")
    args = ap.parse_args()

    if args.account:
        os.environ["ACCOUNT_ID"] = args.account.strip().lower()

    from config import config
    from api.fanvue_connector import FanvueConnector
    from core import fan_memory
    from db import account_id

    aid = account_id()
    blocked = {
        h.strip().lower()
        for h in (getattr(config, "BLOCKED_HANDLES", []) or [])
        if h.strip()
    }

    fv = FanvueConnector()
    me = fv.get_current_user()
    creator_uuid = me.get("uuid")
    print(f"account={aid} creator=@{me.get('handle')} ({creator_uuid})")

    candidates = _collect_candidates(fv, creator_uuid, blocked)
    print(f"\n{len(candidates)} subscriber(s) need welcome opener:\n")
    for c in candidates:
        print(
            f"  @{c['handle']} sub={c['firstSubscribedAt']} → {c['text'][:60]!r}"
        )

    if args.dry_run:
        print("\n(dry-run — no messages sent)")
        return

    if not candidates:
        print("\n✅ nothing to send")
        return

    sent = 0
    for c in candidates:
        fan_uuid = c["fan_uuid"]
        handle = c["handle"]
        text = c["text"]
        try:
            fv.ensure_chat(creator_uuid, fan_uuid)
            time.sleep(1.5)
            fv.send_message(fan_uuid, text)
            fan_memory.mark_welcome_sent(
                fan_uuid, fan_handle=handle, kind="backfill_batch"
            )
            fan_memory.observe_message(fan_uuid, handle, "")
            sent += 1
            print(f"   👋 sent @{handle}: {text}")
        except Exception as exc:
            print(f"   ❌ @{handle}: {exc}")
        time.sleep(max(2.0, args.delay))

    print(f"\n✅ welcomed {sent}/{len(candidates)}")


if __name__ == "__main__":
    main()
