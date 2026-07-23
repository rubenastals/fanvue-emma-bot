"""
Launch Sophia Cler connected to Fanvue (same flow as start_emma.py).

Steps:
  1. If no OAuth tokens for account=sophia → browser OAuth (log in AS SOPHIA)
  2. Verifies API connection
  3. Starts inbox polling (auto-reply)

Usage (Cursor terminal — open the fanvue-emma-bot folder first):
    python scripts/start_sophia.py

Requires .env with FANVUE_CLIENT_ID / FANVUE_CLIENT_SECRET (same as Emma).
If .env has DATABASE_URL (Railway), tokens are stored per account in Postgres.
"""
from __future__ import annotations

import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Must be set before any db / oauth import
os.environ.setdefault("ACCOUNT_ID", "sophia")
os.environ.setdefault("FANVUE_MEDIA_MAP", "data/sophia_fanvue_media_map.json")
os.environ.setdefault("PERSONA_FILE", "personas/sophia.md")


def _has_tokens() -> bool:
    from db import oauth_store

    return bool(oauth_store.load_tokens(aid="sophia"))


def _ensure_account() -> None:
    from db import use_postgres

    if not use_postgres():
        return
    from db.schema import init_schema

    init_schema(seed_account=True)


def run_oauth_login() -> bool:
    print("=" * 60)
    print("STEP 1: Fanvue OAuth — log in as SOPHIA CLER (not Emma)")
    print("=" * 60)
    print("\nBrowser opens → Sophia's creator account → Authorize\n")

    oauth_script = os.path.join(_ROOT, "scripts", "oauth_login.py")
    env = os.environ.copy()
    env["ACCOUNT_ID"] = "sophia"
    result = subprocess.run([sys.executable, oauth_script], cwd=_ROOT, env=env)
    return result.returncode == 0 and _has_tokens()


def verify_api():
    print("\n" + "=" * 60)
    print("STEP 2: Verify Fanvue API")
    print("=" * 60)
    from api.fanvue_connector import FanvueConnector

    fv = FanvueConnector()
    me = fv.get_current_user()
    handle = me.get("handle") or me.get("username")
    name = me.get("displayName") or me.get("name") or ""
    print(f"✅ Connected as @{handle} ({name})")
    print(f"   Creator UUID: {me.get('uuid')}")
    if name and "emma" in (name + str(handle)).lower():
        print("\n⚠️  WARNING: this looks like Emma's account — re-run OAuth as Sophia.")
    return me


def start_polling() -> None:
    print("\n" + "=" * 60)
    print("STEP 3: Start inbox polling (Sophia)")
    print("=" * 60)
    print("Checking unread messages every 10 seconds. Ctrl+C to stop.\n")

    poll_script = os.path.join(_ROOT, "scripts", "poll_inbox.py")
    env = os.environ.copy()
    env["ACCOUNT_ID"] = "sophia"
    env.setdefault("FANVUE_MEDIA_MAP", "data/sophia_fanvue_media_map.json")
    env.setdefault("PERSONA_FILE", "personas/sophia.md")
    raise SystemExit(
        subprocess.call(
            [sys.executable, poll_script, "--interval", "10"],
            cwd=_ROOT,
            env=env,
        )
    )


def main() -> None:
    _ensure_account()

    if not _has_tokens():
        if not run_oauth_login():
            sys.exit(1)
    else:
        print("✅ Fanvue tokens already present for account=sophia")

    try:
        verify_api()
    except Exception as e:
        print(f"❌ API check failed: {e}")
        print("   Re-run: python scripts/start_sophia.py")
        sys.exit(1)

    start_polling()


if __name__ == "__main__":
    main()
