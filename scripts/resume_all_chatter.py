#!/usr/bin/env python3
"""
Resume auto-reply for all connected Fanvue models.

  1. Clear Redis global chatter pause
  2. Postgres: accounts.active = true (rows with oauth)
  3. Railway: redeploy poller services (optional)

Usage:
  python scripts/resume_all_chatter.py
  python scripts/resume_all_chatter.py --skip-railway
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


def _railway_cli(*args: str) -> subprocess.CompletedProcess | None:
    token = (os.getenv("RAILWAY_TOKEN") or "").strip()
    if not token:
        return None
    env = os.environ.copy()
    env["RAILWAY_TOKEN"] = token
    return subprocess.run(
        ["npx", "--yes", "@railway/cli", *args],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def _poller_services() -> list[str]:
    explicit = (os.getenv("RAILWAY_POLLER_SERVICES") or DEFAULT_SERVICES).strip()
    return [s.strip() for s in explicit.split(",") if s.strip()]


def resume_redis() -> bool:
    if not (os.getenv("REDIS_URL") or "").strip():
        print("⚠️  REDIS_URL missing — skip Redis resume")
        return False
    from core.chatter_control import resume_chatter

    resume_chatter(global_pause=True)
    print("✅ Redis: global chatter pause cleared")
    return True


def activate_accounts() -> list[str]:
    if not (os.getenv("DATABASE_URL") or "").strip():
        print("⚠️  DATABASE_URL missing — skip accounts.active=true")
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
                WHERE a.active = FALSE
                ORDER BY a.id
                """
            )
        ).mappings().all()
        for row in rows:
            aids.append(str(row["id"]))
            print(f"📝 accounts.active=true → {row['id']} (@{row.get('handle') or '?'})")
        if aids:
            session.execute(
                text(
                    """
                    UPDATE accounts SET active = TRUE, updated_at = now()
                    WHERE id IN (SELECT account_id FROM oauth_tokens) AND active = FALSE
                    """
                )
            )
    if aids:
        print(f"✅ Postgres: reactivated {len(aids)} account(s)")
    return aids


def redeploy_railway() -> list[str]:
    token = (os.getenv("RAILWAY_TOKEN") or "").strip()
    if not token:
        print("⚠️  RAILWAY_TOKEN missing — skip Railway redeploy")
        return []
    project = (os.getenv("RAILWAY_PROJECT_ID") or "").strip()
    ok: list[str] = []
    for svc in _poller_services():
        args = ["up", "--service", svc, "-y"]
        if project:
            args.extend(["--project", project])
        print(f"🚀 Railway up: {svc}")
        proc = _railway_cli(*args)
        if proc and proc.returncode == 0:
            print(f"   ✅ {svc} redeploy triggered")
            ok.append(svc)
        elif proc:
            print(f"   ❌ {svc}: {(proc.stderr or proc.stdout or '')[:300]}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-railway", action="store_true")
    args = ap.parse_args()

    print("=" * 60)
    print("RESUME ALL CHATTER")
    print("=" * 60)

    resume_redis()
    aids = activate_accounts()
    deployed: list[str] = []
    if not args.skip_railway:
        deployed = redeploy_railway()

    print("\n--- summary ---")
    print(f"accounts reactivated: {aids or '(none)'}")
    print(f"railway redeployed: {deployed or '(none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
