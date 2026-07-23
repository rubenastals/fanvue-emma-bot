"""Pause auto re-engage for one fan until they write a real message.

Usage:
    ACCOUNT_ID=sophia python scripts/pause_fan_reengage.py tommy1299 "robot complaint"
"""
from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))


def main() -> None:
    ap = argparse.ArgumentParser(description="Pause re-engage until fan writes")
    ap.add_argument("handle", help="Fan handle substring")
    ap.add_argument("reason", nargs="?", default="manual", help="Pause reason")
    ap.add_argument("--account", default="", help="ACCOUNT_ID override")
    args = ap.parse_args()

    if args.account:
        os.environ["ACCOUNT_ID"] = args.account.strip().lower()

    from api.fanvue_connector import FanvueConnector
    from core.farewell import mark_conversation_closed, pause_reengage_until_fan_writes

    needle = args.handle.lower().strip()
    fv = FanvueConnector()
    chats = fv.list_chats(size=50)
    fan_uuid = ""
    fan_handle = ""
    for c in chats:
        u = c.get("user") or {}
        h = (u.get("handle") or "").lower()
        if needle in h:
            fan_uuid = u.get("uuid") or ""
            fan_handle = u.get("handle") or ""
            break

    if not fan_uuid:
        print(f"❌ No fan found for handle ~ {needle!r}")
        sys.exit(1)

    pause_reengage_until_fan_writes(fan_uuid, fan_handle=fan_handle, reason=args.reason)
    mark_conversation_closed(fan_uuid, fan_handle=fan_handle, reason=args.reason)
    print(f"✅ Paused re-engage for @{fan_handle} ({fan_uuid}) — reason: {args.reason}")


if __name__ == "__main__":
    main()
