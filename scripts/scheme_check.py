"""
Offline scheme compliance report from conversation logs.

  python scripts/scheme_check.py
  python scripts/scheme_check.py --critic   # also run DeepSeek SCHEME critic

Shows: pack distribution, guard hits, and optional critic SCHEME errors.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from core import convo_log, critic, fan_memory, scheme_guard


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--critic", action="store_true", help="Run DeepSeek critic too")
    ap.add_argument("--limit", type=int, default=15)
    args = ap.parse_args()

    fans = convo_log.all_fan_uuids()
    print(f"Fans with logs: {len(fans)}\n")

    pack_c: Counter = Counter()
    tech_c: Counter = Counter()
    guard_hits = 0
    turns_n = 0
    recheck_hits = 0

    for fid in fans[: args.limit]:
        mem = fan_memory.get(fid) or {}
        handle = mem.get("handle") or fid[:8]
        records = convo_log.read_recent(fid, max_records=30)
        fan_turns = [r for r in records if r.get("type") == "turn"]
        if not fan_turns:
            continue
        print(f"@{handle} — {len(fan_turns)} recent turns")
        for r in fan_turns[-8:]:
            turns_n += 1
            pid = r.get("pack_id") or "?"
            tech = r.get("technique") or "-"
            pack_c[pid] += 1
            if tech != "-":
                tech_c[tech] += 1
            ge = r.get("scheme_errors") or []
            if ge:
                guard_hits += len(ge)
            # Re-run guard on stored reply (works even for pre-meta turns if we pass pack)
            fresh = scheme_guard.check_reply(
                r.get("reply") or "",
                pack_id=r.get("pack_id") or "",
                lock_active=r.get("lock_active"),
                media_attached=bool(r.get("offer")),
                technique=r.get("technique") or "",
            )
            if fresh:
                recheck_hits += len(fresh)
            lock = r.get("lock_active")
            lock_s = "ACTIVE" if lock is True else ("NONE" if lock is False else "?")
            flag = f" ⚠{len(ge)}" if ge else ""
            print(
                f"  pack={pid} tech={tech[:28]} lock={lock_s}{flag} | "
                f"{(r.get('reply') or '')[:70].replace(chr(10), ' ')}"
            )
            for e in ge or fresh[:2]:
                print(f"    · [{e.get('severity')}] {e.get('what')}")

        if args.critic:
            print(f"  critic…", end=" ", flush=True)
            v = critic.review_fan(fid, handle)
            if not v:
                print("no verdict")
            else:
                errs = [
                    e
                    for e in (v.get("errors") or [])
                    if e.get("rule") in ("SCHEME", "SELLING", "HUMANITY")
                ]
                print(
                    f"{v.get('fan_temperature')} "
                    f"scheme_score={v.get('scheme_score', '-')} "
                    f"flags={len(errs)}"
                )
                for e in errs[:5]:
                    print(f"    · [{e.get('rule')}] {e.get('what')}")
        print()

    print("--- summary ---")
    print(f"turns scanned: {turns_n}")
    print(f"logged guard hits: {guard_hits} | recheck hits: {recheck_hits}")
    print("packs:", dict(pack_c.most_common(12)))
    print("techniques:", dict(tech_c.most_common(8)))
    print(
        "\nTip: after chatting, run with --critic. "
        "Live logs show ⚠ scheme_fail when DeepSeek breaks a hard NEVER."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
