"""Inspect one fan thread — Fanvue API + fan_memory + conversation_events.

Usage:
    ACCOUNT_ID=sophia python scripts/inspect_fan.py birbo
    python scripts/inspect_fan.py birbo --account emma
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Inspect fan chat by handle substring")
    ap.add_argument("handle", help="Fan handle substring, e.g. birbo")
    ap.add_argument("--account", default="", help="ACCOUNT_ID override (emma|sophia)")
    ap.add_argument("--messages", type=int, default=40)
    args = ap.parse_args()

    if args.account:
        os.environ["ACCOUNT_ID"] = args.account.strip().lower()

    from db import account_id
    from api.fanvue_connector import FanvueConnector
    from core import fan_memory
    from db import convo_store

    aid = account_id()
    needle = args.handle.lower().strip()
    fv = FanvueConnector()
    me = fv.get_current_user()
    print(f"account={aid} creator=@{me.get('handle')} ({me.get('displayName')})")
    print(f"searching fan handle ~ {needle!r}\n")

    chats = fv.list_chats(size=50)
    match = None
    for c in chats:
        u = c.get("user") or {}
        h = (u.get("handle") or "").lower()
        if needle in h:
            match = c
            break

    if not match:
        print("❌ No chat found in last 50 chats. Try exact handle or check account.")
        # Search fan_memory handles
        from db import fan_memory_store

        all_mem = fan_memory_store.load_all() or {}
        for fid, mem in all_mem.items():
            h = (mem.get("handle") or "").lower()
            if needle in h or needle in fid.lower():
                print(f"  memory hit: {fid} handle={mem.get('handle')!r} name={mem.get('name')!r}")
        sys.exit(1)

    u = match["user"]
    fan_uuid = u["uuid"]
    print(f"✅ fan @{u.get('handle')} uuid={fan_uuid}")
    print(f"   unread={match.get('unreadMessagesCount')} last={match.get('lastMessageAt')}\n")

    mem = fan_memory.get(fan_uuid) or {}
    print("--- CLIENT CARD (fan_memory) ---")
    print(json.dumps(mem, indent=2, ensure_ascii=False)[:4000])

    print("\n--- FANVUE MESSAGES (newest last) ---")
    msgs = list(reversed(fv.get_messages(fan_uuid, size=args.messages)))
    creator_uuid = me.get("uuid")
    for m in msgs:
        s = m.get("sender")
        sid = s.get("uuid") if isinstance(s, dict) else s
        who = "CREATOR" if sid == creator_uuid else "FAN"
        text = (m.get("text") or "").replace("\n", " ")[:200]
        media = ""
        if m.get("hasMedia"):
            media = f" [media price={m.get('price')}]"
        print(f"{m.get('sentAt') or m.get('createdAt')} {who}: {text}{media}")

    print("\n--- CONVERSATION EVENTS (internal) ---")
    events = convo_store.read_recent(fan_uuid, max_records=25)
    if not events:
        print("(none)")
    else:
        for ev in events[-15:]:
            et = ev.get("type") or ev.get("event_type")
            summary = ev.get("summary") or ev.get("reply_preview") or ev.get("pack_id") or ""
            err = ev.get("error") or ev.get("guard_reason") or ""
            line = f"{ev.get('ts')} {et} {summary} {err}".strip()
            print(line[:240])

    # Quick anomaly hints
    print("\n--- ANOMALY HINTS ---")
    hints: list[str] = []
    if aid == "sophia":
        for m in msgs:
            if sid == creator_uuid:
                t = (m.get("text") or "").lower()
                if any(w in t for w in ("emma", "miami girl", "thick", "curvy")):
                    hints.append("Creator message may sound like Emma not Sophia")
                if any(w in t for w in ("hola ", "bebé", "jaja", "guapo", "mira ")):
                    hints.append("Creator replied in Spanish (Sophia should be EN only)")
    dup_times = {}
    for m in msgs:
        if (m.get("sender") == creator_uuid or (isinstance(m.get("sender"), dict) and m["sender"].get("uuid") == creator_uuid)):
            t = (m.get("text") or "")[:80]
            dup_times[t] = dup_times.get(t, 0) + 1
    for t, n in dup_times.items():
        if n > 1:
            hints.append(f"Duplicate creator bubble ({n}x): {t[:60]!r}")

    if mem.get("last_ppv_pending"):
        hints.append(f"PPV pending lock: {mem.get('last_ppv_media_uuid')}")
    if not hints:
        print("No obvious anomalies from heuristics — paste full output for manual review.")
    else:
        for h in hints:
            print(f"⚠️  {h}")


if __name__ == "__main__":
    main()
