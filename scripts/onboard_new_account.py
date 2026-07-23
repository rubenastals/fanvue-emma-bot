"""Onboard a newly connected Fanvue account — welcome + churn fix sweep.

Run once after OAuth / before (or right after) starting the poller.

Usage:
    ACCOUNT_ID=sophia python scripts/onboard_new_account.py --dry-run
    ACCOUNT_ID=sophia python scripts/onboard_new_account.py
    ACCOUNT_ID=sophia python scripts/onboard_new_account.py --welcome-only
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


def _collect_decisions(fv, creator_uuid: str, blocked: set[str]):
    from core import fan_memory
    from core.account_onboard import (
        WelcomeDecision,
        active_subscriber_ids,
        evaluate_welcome,
        list_all_chats,
        repesca_appropriate,
    )

    active = active_subscriber_ids(fv, creator_uuid)
    seen: set[str] = set()
    welcome_rows: list[WelcomeDecision] = []
    churn_rows: list[WelcomeDecision] = []
    repesca_report: list[dict] = []

    def _process(fan_uuid: str, handle: str, source: str, subscription_status: str = ""):
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
        if decision.action == "welcome":
            welcome_rows.append(decision)
        elif decision.action == "churn_fix" and not mem.get("churn_apology_sent_at"):
            churn_rows.append(decision)

        ok, reason = repesca_appropriate(messages, fan_uuid, creator_uuid, mem)
        if int(mem.get("messages") or 0) >= 1:
            repesca_report.append(
                {
                    "handle": handle,
                    "repesca_ok": ok,
                    "reason": reason,
                    "membership": decision.membership,
                }
            )

    for page in range(1, 21):
        batch = fv.list_subscribers(creator_uuid, page=page, size=50)
        if not batch:
            break
        for sub in batch:
            fan_uuid = sub.get("uuid")
            handle = sub.get("handle") or "fan"
            sub_info = sub.get("subscription") or {}
            _process(
                fan_uuid,
                handle,
                "subscriber",
                subscription_status=sub_info.get("status") or "",
            )
        if len(batch) < 50:
            break

    for chat in list_all_chats(fv):
        user = chat.get("user") or {}
        _process(user.get("uuid"), user.get("handle") or "fan", "chat")

    return welcome_rows, churn_rows, repesca_report


def main() -> None:
    ap = argparse.ArgumentParser(description="New-account welcome + churn sweep")
    ap.add_argument("--account", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--welcome-only", action="store_true")
    ap.add_argument("--delay", type=float, default=4.0)
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

    welcome_rows, churn_rows, repesca_report = _collect_decisions(
        fv, creator_uuid, blocked
    )

    print(f"\n=== WELCOME ({len(welcome_rows)} active unopened) ===")
    for row in welcome_rows:
        print(
            f"  @{row.handle} [{row.source}] {row.membership} → {row.text[:55]!r}"
        )

    if not args.welcome_only:
        print(f"\n=== CHURN FIX ({len(churn_rows)} expired wrong-welcome) ===")
        for row in churn_rows:
            print(f"  @{row.handle} [{row.source}] {row.membership} → churn apology")

    live = [r for r in repesca_report if not r["repesca_ok"] and r["reason"] == "thread_live"]
    ready = [r for r in repesca_report if r["repesca_ok"]]
    print(f"\n=== REPRESCA CONTEXT ({len(repesca_report)} chatted fans) ===")
    print(f"  live threads (no nudge yet): {len(live)}")
    print(f"  ok when silence tier hits: {len(ready)}")
    for row in live[:8]:
        print(f"    @{row['handle']} — thread still live")
    if len(live) > 8:
        print(f"    … +{len(live) - 8} more")

    if args.dry_run:
        print("\n(dry-run — no messages sent)")
        return

    if not welcome_rows and not churn_rows:
        print("\n✅ nothing to send")
        return

    sent_w = sent_c = 0
    for row in welcome_rows:
        try:
            fv.ensure_chat(creator_uuid, row.fan_uuid)
            time.sleep(1.5)
            fv.send_message(row.fan_uuid, row.text)
            fan_memory.mark_welcome_sent(
                row.fan_uuid, fan_handle=row.handle, kind="onboard_batch"
            )
            sent_w += 1
            print(f"   👋 @{row.handle}: {row.text}")
        except Exception as exc:
            print(f"   ❌ welcome @{row.handle}: {exc}")
        time.sleep(max(2.0, args.delay))

    if not args.welcome_only:
        for row in churn_rows:
            text = random.choice(_CHURN_TEMPLATES)
            try:
                fv.ensure_chat(creator_uuid, row.fan_uuid)
                time.sleep(1.5)
                fv.send_message(row.fan_uuid, text)
                fan_memory.patch_fanvue_platform(
                    row.fan_uuid,
                    {
                        "churn_apology_sent_at": datetime.now(timezone.utc).isoformat(),
                        "churn_apology_kind": "churn",
                    },
                    fan_handle=row.handle,
                )
                sent_c += 1
                print(f"   💬 churn @{row.handle}: {text}")
            except Exception as exc:
                print(f"   ❌ churn @{row.handle}: {exc}")
            time.sleep(max(2.0, args.delay))

    print(f"\n✅ welcomed {sent_w}, churn fixed {sent_c}")


if __name__ == "__main__":
    main()
