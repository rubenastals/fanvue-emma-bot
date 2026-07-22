#!/usr/bin/env python3
"""
Run one hourly Cursor-cloud review (blocking).

  python scripts/hour_review_once.py           # launch cloud agent
  python scripts/hour_review_once.py --brief   # only write docs/briefs/hour_review_LATEST.md

Needs CURSOR_API_KEY (unless --brief).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Hourly Cursor cloud review")
    ap.add_argument(
        "--brief",
        action="store_true",
        help="Only collect turns + write brief (no agent)",
    )
    args = ap.parse_args()

    from core import hour_review

    if args.brief:
        frames = hour_review._collect_hour_frame(
            minutes=hour_review.HOUR_REVIEW_MINUTES,
            max_fans=hour_review.HOUR_REVIEW_MAX_FANS,
            max_turns=hour_review.HOUR_REVIEW_MAX_TURNS,
        )
        prompt = hour_review.build_hour_prompt(frames)
        hour_review._write_brief(prompt, frames)
        print(
            f"wrote {hour_review._BRIEF_MD} "
            f"(fans={len(frames)} turns={sum(len(f['turns']) for f in frames)})"
        )
        return 0

    # Force sync path
    os.environ["HOUR_REVIEW_ASYNC"] = "0"
    out = hour_review.run_hourly_review()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if out.get("skipped"):
        return 2 if out.get("reason") not in ("no_turns", "disabled") else 0
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
