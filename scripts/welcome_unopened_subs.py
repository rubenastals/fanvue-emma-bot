"""Backfill welcome DMs for subscribers who never opened chat.

Prefer `scripts/onboard_new_account.py` on new account connect — it checks
membership (active vs expired) and skips live threads.

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
    from core.account_onboard import (
        active_subscriber_ids,
        evaluate_welcome,
        list_all_chats,
    )

    active = active_subscriber_ids(fv, creator_uuid)
    seen: set[str] = set()
    out: list[dict] = []

    def _maybe_add(fan_uuid, handle, source, subscription_status=""):
        if not fan_uuid or fan_uuid in seen:
            return
        if (handle or "").lower() in blocked:
            return
        seen.add(fan_uuid)
        mem = fan_memory.get(fan_uuid) or {}
        try:
            insights = fv.get_fan_insights(fan_uuid)
        except Exception:
            insights = {}
        try:
            messages = fv.get_messages(fan_uuid, size=12)
        except Exception:
            messages = []
        decision = evaluate_welcome(
            fan_uuid=fan_uuid,
            handle=handle,
            creator_uuid=creator_uuid,
            messages=messages,
            mem=mem,
            insights=insights,
            in_active_sub_list=fan_uuid in active,
            subscription_status=subscription_status,
            source=source,
        )
        if decision.action != "welcome":
            return
        out.append(
            {
                "fan_uuid": fan_uuid,
                "handle": handle,
                "source": source,
                "text": decision.text,
                "reason": decision.reason,
            }
        )

    for page in range(1, 21):
        batch = fv.list_subscribers(creator_uuid, page=page, size=50)
        if not batch:
            break
        for sub in batch:
            sub_info = sub.get("subscription") or {}
            _maybe_add(
                sub.get("uuid"),
                sub.get("handle") or "fan",
                "subscriber",
                subscription_status=sub_info.get("status") or "",
            )
        if len(batch) < 50:
            break

    for chat in list_all_chats(fv):
        user = chat.get("user") or {}
        _maybe_add(user.get("uuid"), user.get("handle") or "fan", "chat")

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
    print(f"\n{len(candidates)} active unopened sub(s) need welcome:\n")
    for c in candidates:
        print(
            f"  @{c['handle']} [{c['source']}] ({c['reason']}) → {c['text'][:60]!r}"
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
            sent += 1
            print(f"   👋 sent @{handle}: {text}")
        except Exception as exc:
            print(f"   ❌ @{handle}: {exc}")
        time.sleep(max(2.0, args.delay))

    print(f"\n✅ welcomed {sent}/{len(candidates)}")


if __name__ == "__main__":
    main()
