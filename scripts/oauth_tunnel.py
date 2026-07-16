"""
Fanvue OAuth via Cloudflare Tunnel (real HTTPS, no cert warnings).

1. Starts local callback on :8000
2. Opens a public https://xxxx.trycloudflare.com tunnel
3. You add that callback URL in Fanvue Builder (one time for this session)
4. Browser opens → Authorize → tokens saved automatically

Usage:
    python scripts/oauth_tunnel.py
"""
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

from api.fanvue_oauth import (
    clear_pending_oauth,
    exchange_code_for_tokens,
    generate_pkce,
    save_pending_oauth,
)
from config import config

_RESULT = {"ok": False, "error": None, "code": None, "state": None}
_EXPECTED = {"state": None, "verifier": None}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/oauth/callback":
            self.send_response(204)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]
        desc = params.get("error_description", [None])[0]

        if error:
            _RESULT["error"] = f"{error}: {desc or ''}"
            self._html(400, f"OAuth error: {error}")
            return

        if not code or state != _EXPECTED["state"]:
            self._html(400, "Invalid callback. Close tabs and retry.")
            return

        try:
            exchange_code_for_tokens(code, _EXPECTED["verifier"])
            clear_pending_oauth()
            _RESULT["ok"] = True
            self._html(200, "Fanvue connected! Return to the terminal.")
        except Exception as exc:
            _RESULT["error"] = str(exc)
            self._html(500, f"Token exchange failed: {exc}")

    def _html(self, status, msg):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())
        print(msg)

    def log_message(self, *args):
        pass


def start_server():
    server = HTTPServer(("127.0.0.1", 8000), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def start_tunnel():
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", "http://127.0.0.1:8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    public_url = None
    started = time.time()
    while time.time() - started < 45:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                break
            continue
        print(f"  [tunnel] {line.rstrip()}")
        m = re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", line)
        if m:
            public_url = m.group(1)
            break
    return proc, public_url


def main():
    # Free port if needed
    try:
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 8000))
        s.close()
    except OSError:
        print("Port 8000 busy — killing listeners...")
        os.system('for /f "tokens=5" %a in (\'netstat -ano ^| findstr :8000 ^| findstr LISTENING\') do taskkill /F /PID %a >nul 2>&1')
        time.sleep(2)

    print("=" * 60)
    print("FANVUE OAUTH + CLOUDFLARE TUNNEL")
    print("=" * 60)

    server = start_server()
    print("\n1) Local callback server on :8000")
    print("2) Starting Cloudflare tunnel...")

    tunnel, public_url = start_tunnel()
    if not public_url:
        print("ERROR: could not get Cloudflare public URL")
        server.shutdown()
        sys.exit(1)

    redirect_uri = f"{public_url}/oauth/callback"
    print(f"\n3) Public callback URL:\n   {redirect_uri}\n")
    print(">>> ACTION REQUIRED <<<")
    print("In Fanvue Builder → your app → Redirect URIs:")
    print(f"  ADD: {redirect_uri}")
    print("  (you can keep the localhost one too)")
    print("  SAVE the app.\n")

    # Non-interactive: --yes / FANVUE_OAUTH_AUTO=1 skips the Enter prompt
    # (gives you ~25s to save the Redirect URI in Builder first).
    if "--yes" in sys.argv or os.environ.get("FANVUE_OAUTH_AUTO") == "1":
        wait_s = int(os.environ.get("FANVUE_OAUTH_WAIT", "25"))
        print(f"(auto) waiting {wait_s}s for you to save Redirect URI in Builder...")
        time.sleep(wait_s)
    else:
        input("Press Enter AFTER you have saved the Redirect URI in Builder...")

    pkce = generate_pkce()
    state = secrets.token_hex(16)
    _EXPECTED["state"] = state
    _EXPECTED["verifier"] = pkce["code_verifier"]
    save_pending_oauth(state, pkce["code_verifier"])

    # Build auth URL with THIS redirect (override config for this run)
    from urllib.parse import urlencode
    params = {
        "client_id": config.FANVUE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": config.FANVUE_OAUTH_SCOPES,
        "state": state,
        "code_challenge": pkce["code_challenge"],
        "code_challenge_method": "S256",
    }
    auth_url = f"{config.FANVUE_AUTH_URL}?{urlencode(params)}"

    # Patch exchange to use this redirect_uri
    import api.fanvue_oauth as oauth_mod
    original_redirect = config.FANVUE_REDIRECT_URI
    config.FANVUE_REDIRECT_URI = redirect_uri

    print("4) Opening Fanvue authorize page...")
    webbrowser.open(auth_url)
    print("   Log in as CREATOR and click Authorize.\n")
    print("Waiting for callback (up to 3 minutes)...")

    deadline = time.time() + 180
    while time.time() < deadline and not _RESULT["ok"] and not _RESULT["error"]:
        time.sleep(1)

    config.FANVUE_REDIRECT_URI = original_redirect
    server.shutdown()
    tunnel.terminate()

    if _RESULT["ok"]:
        print("\nOK — Fanvue connected!")
        print("Next: python scripts/test_fanvue_api.py")
        print("Then:  python scripts/start_emma.py")
        sys.exit(0)

    print(f"\nFailed: {_RESULT.get('error') or 'timeout — did you authorize and save the Redirect URI?'}")
    sys.exit(1)


if __name__ == "__main__":
    main()
