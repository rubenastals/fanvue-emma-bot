"""
Wait for the Fanvue API to come back online.

Polls GET /users/me every INTERVAL seconds until it returns 200,
then prints the creator profile. Fanvue was returning 504 (server-side
outage) — this avoids manual retrying.

Usage:
    python scripts/wait_for_fanvue.py
    python scripts/wait_for_fanvue.py --interval 60 --max-minutes 120
"""
import argparse
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

import requests
from config import config
from api.fanvue_oauth import get_valid_access_token


def check_once() -> tuple:
    """Returns (status_code, body_or_error)."""
    try:
        tok = get_valid_access_token()
        r = requests.get(
            config.FANVUE_BASE_URL + "/users/me",
            headers={
                "Authorization": f"Bearer {tok}",
                "X-Fanvue-API-Version": config.FANVUE_API_VERSION,
            },
            timeout=20,
        )
        return r.status_code, r
    except Exception as e:
        return None, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--max-minutes", type=int, default=120)
    args = parser.parse_args()

    deadline = time.time() + args.max_minutes * 60
    attempt = 0

    print(f"Waiting for Fanvue API (checking every {args.interval}s, up to {args.max_minutes} min)...")

    while time.time() < deadline:
        attempt += 1
        status, result = check_once()
        stamp = time.strftime("%H:%M:%S")

        if status == 200:
            me = result.json()
            print(f"\n[{stamp}] ✅ FANVUE API IS BACK — 200 OK")
            print(f"   Creator: @{me.get('handle')} ({me.get('displayName')})")
            print(f"   UUID:    {me.get('uuid')}")
            print("\nReady. Next: python scripts/start_emma.py")
            return 0

        if status in (401, 403):
            print(f"\n[{stamp}] ⚠️  Auth problem (status {status}) — token may need re-login.")
            print("   Run: python scripts/oauth_tunnel.py")
            return 1

        label = status if status else f"conn-error ({result})"
        print(f"[{stamp}] attempt {attempt}: not ready (status={label})")
        time.sleep(args.interval)

    print("\nTimed out waiting for Fanvue. Try again later.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
