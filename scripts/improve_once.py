"""
Continuous improvement — one command, no reading chats one-by-one.

Usage:
    python scripts/improve_once.py                 # scan + DeepSeek Soft/Hard board
    python scripts/improve_once.py --apply-soft    # approve pending lessons + Cursor autofix
    python scripts/improve_once.py --write-briefs  # write Hard briefs under docs/briefs/
    python scripts/improve_once.py --all           # digest + soft apply + hard briefs

Flow (automated, supervised):
  Live chats → DeepSeek critic (already) → this board ranks Soft/Hard
  Soft: applied here (lessons + autofix agent)
  Hard: brief files → you open Cursor once → approve merge/deploy
"""
from __future__ import annotations

import argparse
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

from core import improve_board


def main() -> None:
    ap = argparse.ArgumentParser(description="Emma continuous improvement board")
    ap.add_argument("--apply-soft", action="store_true", help="approve lessons + run autofix")
    ap.add_argument("--write-briefs", action="store_true", help="write Hard redesign briefs")
    ap.add_argument("--all", action="store_true", help="digest + soft + briefs")
    ap.add_argument(
        "--no-deepseek",
        action="store_true",
        help="skip DeepSeek classification (stats only)",
    )
    ap.add_argument("--max-fixes", type=int, default=2, help="max Cursor autofix runs")
    args = ap.parse_args()

    apply_soft = args.apply_soft or args.all
    write_briefs = args.write_briefs or args.all

    print("→ Building improve board from live critic/lessons/autofix…")
    board = improve_board.build_board(ask_deepseek=not args.no_deepseek)
    path = improve_board.save_board(board)
    soft_n = len((board.get("proposals") or {}).get("soft") or [])
    hard_n = len((board.get("proposals") or {}).get("hard") or [])
    print(f"✓ Board saved: {path}")
    print(
        f"  critic rules: {board.get('critic_rules') or {}} | "
        f"lessons pending: {len(board.get('pending_lessons') or [])} | "
        f"autofix pending: {len(board.get('autofix_pending') or [])}"
    )
    print(f"  DeepSeek proposals: Soft={soft_n} Hard={hard_n}")

    if soft_n:
        print("\nSOFT:")
        for p in (board.get("proposals") or {}).get("soft") or []:
            print(f"  · [{p.get('action')}] {p.get('title')}: {p.get('detail')}")
    if hard_n:
        print("\nHARD (need your OK later):")
        for p in (board.get("proposals") or {}).get("hard") or []:
            print(f"  · {p.get('title')}: {p.get('problem')}")

    if apply_soft:
        print("\n→ Applying Soft…")
        activated = improve_board.approve_all_pending_lessons(max_n=10)
        if activated:
            for t in activated:
                print(f"  ✅ lesson on: {t[:100]}")
        else:
            print("  · no pending lessons to approve")

        # Cursor autofix for queued code tweaks
        from core import auto_fix as autofix_core
        import subprocess

        pending = autofix_core.pending()
        if pending:
            print(f"  → Cursor autofix (max {args.max_fixes})…")
            r = subprocess.run(
                [
                    sys.executable,
                    "scripts/auto_fix.py",
                    "--run",
                    "--max",
                    str(max(1, args.max_fixes)),
                ],
                cwd=_ROOT,
            )
            if r.returncode == 0:
                print(
                    "  ✅ autofix finished. Review `git diff`, then deploy when ready:\n"
                    "     git push && railway up --service poller"
                )
            else:
                print("  · autofix exited non-zero (check CURSOR_API_KEY / queue)")
        else:
            print("  · autofix queue empty")

    if write_briefs:
        paths = improve_board.write_hard_briefs(board)
        if paths:
            print(f"\n✓ Hard briefs ({len(paths)}):")
            for p in paths:
                print(f"  · {p}")
            print(
                "\nOpen the brief file, paste into a Cursor chat (redesign agent), "
                "review the PR/diff, then YOU say merge + deploy."
            )
        else:
            print("\n· No Hard proposals — no briefs written.")

    print(
        "\nDone. Next time you only need:\n"
        "  python scripts/improve_once.py --all"
    )


if __name__ == "__main__":
    main()
