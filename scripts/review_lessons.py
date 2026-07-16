"""
Review the learning loop: approve/reject global lessons, see fan lessons.

Usage:
    python scripts/review_lessons.py                # show pending + active
    python scripts/review_lessons.py --approve 0    # activate pending lesson #0
    python scripts/review_lessons.py --reject 1     # discard pending lesson #1
    python scripts/review_lessons.py --remove 2     # deactivate active lesson #2
    python scripts/review_lessons.py --fans         # show per-fan lessons
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from core import lessons


def main() -> None:
    ap = argparse.ArgumentParser(description="Review learned lessons")
    ap.add_argument("--approve", type=int, default=None)
    ap.add_argument("--reject", type=int, default=None)
    ap.add_argument("--remove", type=int, default=None)
    ap.add_argument("--fans", action="store_true")
    args = ap.parse_args()

    if args.approve is not None:
        text = lessons.approve_global(args.approve)
        print(f"✅ activated: {text}" if text else "❌ bad index")
        return
    if args.reject is not None:
        text = lessons.reject_global(args.reject)
        print(f"🗑️ rejected: {text}" if text else "❌ bad index")
        return
    if args.remove is not None:
        text = lessons.remove_active(args.remove)
        print(f"🗑️ deactivated: {text}" if text else "❌ bad index")
        return

    if args.fans:
        data = lessons._load()  # noqa: SLF001
        per_fan = data.get("per_fan") or {}
        if not per_fan:
            print("No per-fan lessons yet.")
        for uuid, items in per_fan.items():
            print(f"\n@fan {uuid[:13]}…")
            for l in items:
                print(f"  - {l['text']}")
        return

    act = lessons.active()
    pen = lessons.pending()
    print(f"ACTIVE global lessons ({len(act)}):")
    for i, l in enumerate(act):
        print(f"  [{i}] {l['text']}")
    print(f"\nPENDING approval ({len(pen)}):")
    for i, l in enumerate(pen):
        src = f" (from @{l.get('source_fan')})" if l.get("source_fan") else ""
        print(f"  [{i}] {l['text']}{src}")
    if pen:
        print("\nApprove with: python scripts/review_lessons.py --approve N")


if __name__ == "__main__":
    main()
