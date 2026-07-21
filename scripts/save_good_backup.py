#!/usr/bin/env python3
"""
Save a known-good bot snapshot as an annotated git tag (and push it).

Usage:
  python scripts/save_good_backup.py "Spanish + PPV attach stable"
  python scripts/save_good_backup.py --name good-20260722-night "note"

When Ruben says the bot is going well, run this BEFORE more experiments.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAST_GOOD = ROOT / "backups" / "LAST_GOOD.txt"


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def _slug(text: str, max_len: int = 32) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return (s or "ok")[:max_len]


def main() -> int:
    ap = argparse.ArgumentParser(description="Tag + push a good Emma backup")
    ap.add_argument("note", nargs="?", default="known-good", help="Why this is good")
    ap.add_argument("--name", help="Tag name (default: good-YYYYMMDD-HHMM-<slug>)")
    ap.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow uncommitted changes (tags HEAD commit only — dirty files NOT included)",
    )
    ap.add_argument("--no-push", action="store_true", help="Tag locally only")
    args = ap.parse_args()

    status = _run(["git", "status", "--porcelain"], check=False)
    # Only block on tracked changes; untracked noise (??) is OK
    dirty_tracked = [
        ln
        for ln in (status.stdout or "").splitlines()
        if ln.strip() and not ln.startswith("??")
    ]
    if dirty_tracked and not args.allow_dirty:
        print("Tracked files dirty. Commit first, or pass --allow-dirty.")
        print("\n".join(dirty_tracked))
        return 2

    head = _run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    branch = _run(["git", "branch", "--show-current"], check=False).stdout.strip() or "detached"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    tag = args.name or f"good-{stamp}-{_slug(args.note)}"
    if not tag.startswith("good-"):
        tag = f"good-{tag}"

    existing = _run(["git", "tag", "-l", tag], check=False).stdout.strip()
    if existing:
        print(f"Tag already exists: {tag}")
        return 3

    msg = (
        f"GOOD BACKUP\n\n"
        f"note: {args.note}\n"
        f"commit: {head}\n"
        f"branch: {branch}\n"
        f"utc: {datetime.now(timezone.utc).isoformat()}\n"
    )
    _run(["git", "tag", "-a", tag, "-m", msg])
    print(f"Tagged {tag} -> {head}")

    if not args.no_push:
        push = _run(["git", "push", "origin", tag], check=False)
        if push.returncode != 0:
            print(push.stderr or push.stdout)
            print("Tag created locally but push failed.")
            return 4
        print(f"Pushed origin {tag}")

    LAST_GOOD.parent.mkdir(parents=True, exist_ok=True)
    LAST_GOOD.write_text(
        f"{tag}\n{head}\n{args.note}\n{datetime.now(timezone.utc).isoformat()}\n",
        encoding="utf-8",
    )
    print(f"Recorded {LAST_GOOD.relative_to(ROOT)}")
    print("Restore with: python scripts/restore_good_backup.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
