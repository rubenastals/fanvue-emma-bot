#!/usr/bin/env python3
"""
Restore the bot to a known-good git tag.

Usage:
  python scripts/restore_good_backup.py              # list + restore LAST_GOOD
  python scripts/restore_good_backup.py --list
  python scripts/restore_good_backup.py good-20260722-0033-ok
  python scripts/restore_good_backup.py --deploy     # restore + railway up poller

Safe default: creates/switches branch restore/<tag> from the tag (no force-reset).
Use --hard only when you explicitly want main reset to the tag (destructive).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
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


def _list_tags() -> list[str]:
    out = _run(["git", "tag", "-l", "good-*", "--sort=-creatordate"], check=False)
    return [t for t in (out.stdout or "").splitlines() if t.strip()]


def _last_good_tag() -> str | None:
    if LAST_GOOD.exists():
        line = LAST_GOOD.read_text(encoding="utf-8").splitlines()
        if line:
            return line[0].strip()
    tags = _list_tags()
    return tags[0] if tags else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Restore a good Emma backup tag")
    ap.add_argument("tag", nargs="?", help="Tag name (default: LAST_GOOD / newest good-*)")
    ap.add_argument("--list", action="store_true", help="List good-* tags and exit")
    ap.add_argument(
        "--hard",
        action="store_true",
        help="DESTRUCTIVE: reset current branch to tag (requires clean tree)",
    )
    ap.add_argument(
        "--deploy",
        action="store_true",
        help="After restore, railway up --service poller -y",
    )
    args = ap.parse_args()

    tags = _list_tags()
    if args.list or (not args.tag and not LAST_GOOD.exists() and not tags):
        if not tags:
            print("No good-* tags yet. Save one with: python scripts/save_good_backup.py")
            return 1
        print("Known-good backups (newest first):")
        for t in tags:
            tip = _run(["git", "rev-list", "-n", "1", "--abbrev-commit", t], check=False)
            subj = _run(["git", "log", "-1", "--format=%s", t], check=False)
            print(f"  {t}  ({(tip.stdout or '').strip()})  {(subj.stdout or '').strip()[:60]}")
        if LAST_GOOD.exists():
            print(f"\nLAST_GOOD -> {LAST_GOOD.read_text(encoding='utf-8').splitlines()[0]}")
        return 0

    tag = args.tag or _last_good_tag()
    if not tag:
        print("No backup tag found.")
        return 1
    if not tag.startswith("good-"):
        tag = f"good-{tag}"

    exists = _run(["git", "tag", "-l", tag], check=False).stdout.strip()
    if not exists:
        # try fetch
        _run(["git", "fetch", "origin", "tag", tag], check=False)
        exists = _run(["git", "tag", "-l", tag], check=False).stdout.strip()
    if not exists:
        print(f"Unknown tag: {tag}")
        print("Use --list to see good-* tags")
        return 2

    dirty = bool(_run(["git", "status", "--porcelain"], check=False).stdout.strip())
    if dirty:
        print("Working tree dirty — commit or stash before restore.")
        return 3

    if args.hard:
        print(f"HARD reset current branch to {tag}")
        _run(["git", "reset", "--hard", tag])
    else:
        branch = f"restore/{tag}"
        # Recreate branch from tag
        _run(["git", "branch", "-D", branch], check=False)
        _run(["git", "checkout", "-B", branch, tag])
        print(f"Checked out {branch} at {tag}")
        print("When happy: merge to main or: git checkout main && git reset --hard " + tag)

    head = _run(["git", "rev-parse", "--short", "HEAD"]).stdout.strip()
    print(f"Now at {head} ({tag})")

    if args.deploy:
        print("Deploying poller…")
        dep = _run(["railway", "up", "--service", "poller", "-y"], check=False)
        print(dep.stdout or "")
        if dep.returncode != 0:
            print(dep.stderr or "railway up failed")
            return 4
        print("Deploy kicked off.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
