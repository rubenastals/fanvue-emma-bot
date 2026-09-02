#!/usr/bin/env python3
"""
Stop auto-reply (chatter) for all connected Fanvue models.

Actions (best-effort, in order):
  1. Railway: `down` on each poller service (immediate — stops containers)
  2. Redis: global chatter pause key (survives redeploy until cleared)
  3. Postgres: accounts.active = false for all rows with oauth tokens

Requires (any of):
  RAILWAY_TOKEN (+ optional RAILWAY_PROJECT_ID) — stop poller services
  REDIS_URL — set global pause flag
  DATABASE_URL — mark accounts inactive

Usage:
  python scripts/stop_all_chatter.py
  python scripts/stop_all_chatter.py --dry-run
  python scripts/stop_all_chatter.py --skip-railway   # Redis/DB only
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, ".env"))

DEFAULT_SERVICES = "poller,poller-sophia"


def _railway_cli(*args: str, dry_run: bool = False) -> subprocess.CompletedProcess | None:
    token = (os.getenv("RAILWAY_TOKEN") or "").strip()
    if not token:
        return None
    cmd = ["npx", "--yes", "@railway/cli", *args]
    if dry_run:
        print(f"  [dry-run] RAILWAY_TOKEN=*** {' '.join(cmd)}")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    env = os.environ.copy()
    env["RAILWAY_TOKEN"] = token
    return subprocess.run(cmd, cwd=_ROOT, env=env, capture_output=True, text=True)


def _discover_poller_services() -> list[str]:
    explicit = (os.getenv("RAILWAY_POLLER_SERVICES") or DEFAULT_SERVICES).strip()
    names = [s.strip() for s in explicit.split(",") if s.strip()]
    if not (os.getenv("RAILWAY_TOKEN") or "").strip():
        return names
    proc = _railway_cli("service", "list", "--json")
    if not proc or proc.returncode != 0:
        return names
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return names
    found: list[str] = []
    for row in data if isinstance(data, list) else []:
        name = str(row.get("name") or "")
        if "poller" in name.lower():
            found.append(name)
    return found or names


def stop_railway_pollers(*, dry_run: bool) -> list[str]:
    token = (os.getenv("RAILWAY_TOKEN") or "").strip()
    if not token:
        print("⚠️  RAILWAY_TOKEN missing — skip Railway stop")
        return []
    project = (os.getenv("RAILWAY_PROJECT_ID") or "").strip()
    stopped: list[str] = []
    for svc in _discover_poller_services():
        args = ["down", "--service", svc, "-y"]
        if project:
            args.extend(["--project", project])
        print(f"🛑 Railway down: {svc}")
        proc = _railway_cli(*args, dry_run=dry_run)
        if proc is None:
            continue
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            print(f"   ❌ {svc}: {err[:300]}")
        else:
            print(f"   ✅ {svc} deployment removed")
            stopped.append(svc)
    return stopped


def pause_redis(*, dry_run: bool, reason: str) -> bool:
    if not (os.getenv("REDIS_URL") or "").strip():
        print("⚠️  REDIS_URL missing — skip Redis pause")
        return False
    if dry_run:
        print(f"  [dry-run] Redis SET chatter:paused:global = {reason!r}")
        return True
    from core.chatter_control import pause_chatter

    pause_chatter(global_pause=True, reason=reason)
    print("✅ Redis: global chatter pause set")
    return True


def deactivate_accounts(*, dry_run: bool) -> list[str]:
    if not (os.getenv("DATABASE_URL") or "").strip():
        print("⚠️  DATABASE_URL missing — skip accounts.active=false")
        return []
    from sqlalchemy import text

    from db.pg import session_scope

    aids: list[str] = []
    with session_scope() as session:
        rows = session.execute(
            text(
                """
                SELECT a.id, a.handle
                FROM accounts a
                INNER JOIN oauth_tokens o ON o.account_id = a.id
                WHERE a.active = TRUE
                ORDER BY a.id
                """
            )
        ).mappings().all()
        for row in rows:
            aids.append(str(row["id"]))
            print(f"📝 accounts.active=false → {row['id']} (@{row.get('handle') or '?'})")
        if aids and not dry_run:
            session.execute(
                text(
                    """
                    UPDATE accounts SET active = FALSE, updated_at = now()
                    WHERE id IN (SELECT account_id FROM oauth_tokens) AND active = TRUE
                    """
                )
            )
    if dry_run and not aids:
        print("  [dry-run] no active connected accounts in DB")
    elif aids and not dry_run:
        print(f"✅ Postgres: deactivated {len(aids)} account(s)")
    return aids


def main() -> int:
    ap = argparse.ArgumentParser(description="Stop chatter for all connected models")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-railway", action="store_true")
    ap.add_argument("--reason", default="operator stop_all_chatter")
    args = ap.parse_args()

    print("=" * 60)
    print("STOP ALL CHATTER")
    print("=" * 60)

    stopped: list[str] = []
    if not args.skip_railway:
        stopped = stop_railway_pollers(dry_run=args.dry_run)
    pause_redis(dry_run=args.dry_run, reason=args.reason)
    aids = deactivate_accounts(dry_run=args.dry_run)

    print("\n--- summary ---")
    print(f"railway stopped: {stopped or '(none)'}")
    print(f"accounts deactivated: {aids or '(none)'}")

    if not stopped and not aids and not (os.getenv("REDIS_URL") or "").strip():
        print(
            "\n❌ No credentials — add RAILWAY_TOKEN (and/or REDIS_URL, DATABASE_URL) "
            "to Cursor Cloud secrets or .env, then re-run."
        )
        return 1
    if args.dry_run:
        print("\n(dry-run — no changes applied)")
    else:
        print("\n✅ Chatter off. Resume: python scripts/resume_all_chatter.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
