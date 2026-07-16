"""
Launch Emma connected to Fanvue (no webhooks, no Docker).

Steps:
  1. If no OAuth tokens → starts login server + opens browser
  2. Waits for you to authorize (one-time)
  3. Verifies API connection
  4. Starts inbox polling (auto-reply)

Usage:
    python scripts/start_emma.py
"""
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

TOKEN_FILE = os.path.join(_ROOT, ".fanvue_tokens.json")


def has_tokens() -> bool:
    return os.path.exists(TOKEN_FILE)


def run_oauth_login():
    print("=" * 60)
    print("STEP 1: Fanvue OAuth login")
    print("=" * 60)
    print("\nA browser window will open — authorize with your creator account.\n")

    oauth_script = os.path.join(_ROOT, "scripts", "oauth_login.py")
    result = subprocess.run([sys.executable, oauth_script], cwd=_ROOT)
    return result.returncode == 0 and has_tokens()


def verify_api():
    print("\n" + "=" * 60)
    print("STEP 2: Verify Fanvue API")
    print("=" * 60)
    from api.fanvue_connector import FanvueConnector
    fv = FanvueConnector()
    me = fv.get_current_user()
    print(f"✅ Connected as @{me.get('handle')} ({me.get('displayName')})")
    print(f"   Creator UUID: {me.get('uuid')}")
    return me


def start_polling():
    print("\n" + "=" * 60)
    print("STEP 3: Start inbox polling (auto-reply)")
    print("=" * 60)
    print("Emma will check for unread messages every 10 seconds.")
    print("Press Ctrl+C to stop.\n")

    poll_script = os.path.join(_ROOT, "scripts", "poll_inbox.py")
    # Use subprocess (not execv): Windows splits paths with spaces under execv.
    raise SystemExit(
        subprocess.call(
            [sys.executable, poll_script, "--interval", "10"],
            cwd=_ROOT,
        )
    )


def main():
    if not has_tokens():
        if not run_oauth_login():
            sys.exit(1)
    else:
        print("✅ Fanvue tokens already present")

    try:
        verify_api()
    except Exception as e:
        print(f"❌ API check failed: {e}")
        print("   Re-run: python scripts/oauth_login.py")
        sys.exit(1)

    start_polling()


if __name__ == "__main__":
    main()
