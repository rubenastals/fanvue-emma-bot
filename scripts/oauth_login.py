"""
Fanvue OAuth login — paste-the-URL mode (most reliable on Windows).

Fanvue often fails with local HTTPS certs. This flow:
  1. Opens the Fanvue authorize page
  2. After you click Authorize, the browser redirects to localhost
     (page may look broken — that's OK)
  3. You COPY the full URL from the address bar and PASTE it here

Usage:
    python scripts/oauth_login.py
"""
import os
import secrets
import sys
import webbrowser
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

from api.fanvue_oauth import (
    build_authorization_url,
    clear_pending_oauth,
    exchange_code_for_tokens,
    generate_pkce,
    save_pending_oauth,
)
from config import config


def main():
    if not config.FANVUE_CLIENT_ID or not config.FANVUE_CLIENT_SECRET:
        print("ERROR: missing FANVUE_CLIENT_ID / FANVUE_CLIENT_SECRET in .env")
        sys.exit(1)

    clear_pending_oauth()
    pkce = generate_pkce()
    state = secrets.token_hex(16)
    save_pending_oauth(state, pkce["code_verifier"])
    auth_url = build_authorization_url(state, pkce["code_challenge"])

    print("=" * 60)
    print("FANVUE OAUTH LOGIN")
    print("=" * 60)
    print("\nIn Fanvue Builder, Redirect URI must be EXACTLY:")
    print(f"  {config.FANVUE_REDIRECT_URI}")
    print("\nSteps:")
    print("  1. Browser opens → log in as CREATOR → click Authorize")
    print("  2. Browser goes to localhost (page may look broken / certificate warning)")
    print("  3. COPY the FULL URL from the address bar (starts with https://localhost...)")
    print("  4. PASTE it below and press Enter\n")

    print("Opening browser...")
    webbrowser.open(auth_url)
    print(f"\nIf browser did not open, go to:\n{auth_url}\n")

    pasted = input("Paste the full redirect URL here:\n> ").strip()
    if not pasted:
        print("Empty input. Exiting.")
        sys.exit(1)

    # Allow pasting just the query string too
    if pasted.startswith("?"):
        pasted = config.FANVUE_REDIRECT_URI + pasted
    if "://" not in pasted and "code=" in pasted:
        pasted = config.FANVUE_REDIRECT_URI + ("&" if pasted.startswith("code=") else "?") + pasted.lstrip("?&")

    parsed = urlparse(pasted)
    params = parse_qs(parsed.query)
    code = params.get("code", [None])[0]
    returned_state = params.get("state", [None])[0]
    error = params.get("error", [None])[0]
    error_desc = params.get("error_description", [None])[0]

    if error:
        print(f"Fanvue returned an error: {error}")
        if error_desc:
            print(f"  {error_desc}")
        sys.exit(1)

    if not code:
        print("No 'code=' found in that URL.")
        print("Make sure you copied the address bar AFTER authorizing, not the Fanvue auth page.")
        sys.exit(1)

    if returned_state != state:
        print(f"State mismatch (got {returned_state}, expected {state}).")
        print("Close old tabs and run this script again from scratch.")
        sys.exit(1)

    try:
        exchange_code_for_tokens(code, pkce["code_verifier"])
        clear_pending_oauth()
    except Exception as exc:
        print(f"Token exchange failed: {exc}")
        if hasattr(exc, "response") and exc.response is not None:
            print(f"  Response: {exc.response.text[:500]}")
        sys.exit(1)

    print("\nOK — Fanvue connected!")
    print("Next:")
    print("  python scripts/test_fanvue_api.py")
    print("  python scripts/start_emma.py")


if __name__ == "__main__":
    main()
