"""Run DeepSeek critic on recent fans, then print a short digest."""
from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

from core import convo_log, critic, fan_memory


def main() -> None:
    fans = convo_log.all_fan_uuids()
    print(f"Fans with logs: {len(fans)}")
    n = 0
    for fid in fans[:25]:
        mem = fan_memory.get(fid) or {}
        handle = mem.get("handle") or fid[:8]
        print(f"  critic @{handle}…", end=" ", flush=True)
        v = critic.review_fan(fid, handle)
        if not v:
            print("no verdict")
            continue
        errs = v.get("errors") or []
        temp = v.get("fan_temperature")
        gl = (v.get("global_lesson") or "")[:90]
        print(f"{temp} errs={len(errs)}")
        for e in errs:
            print(f"    · [{e.get('rule')} s{e.get('severity')}] {e.get('what')}")
        if gl:
            print(f"    global: {gl}")
        n += 1
    print(f"Done: {n} reviews")


if __name__ == "__main__":
    main()
