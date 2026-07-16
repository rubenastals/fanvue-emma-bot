"""
OAuth callback server that exchanges the code for tokens IMMEDIATELY
(no lost-code window). Used with the Cloudflare tunnel.

Reads the pending session (.oauth_tunnel_session.json) for redirect_uri,
state and code_verifier.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

import requests
from config import config
from api.fanvue_oauth import _basic_auth_header, _save_tokens

SESSION_FILE = os.path.join(_ROOT, ".oauth_tunnel_session.json")
DONE_FILE = os.path.join(_ROOT, ".oauth_done.json")


def _load_session():
    with open(SESSION_FILE, encoding="utf-8") as f:
        return json.load(f)


class H(BaseHTTPRequestHandler):
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

        if error:
            self._html(400, f"OAuth error: {error}")
            return
        if not code:
            self.send_response(204)
            self.end_headers()
            return

        session = _load_session()
        if state != session.get("state"):
            self._html(400, "State mismatch — restart login.")
            return

        try:
            resp = requests.post(
                config.FANVUE_TOKEN_URL,
                headers={
                    "Authorization": f"Basic {_basic_auth_header()}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": session["redirect_uri"],
                    "code_verifier": session["code_verifier"],
                },
                timeout=30,
            )
            resp.raise_for_status()
            _save_tokens(resp.json())
            with open(DONE_FILE, "w", encoding="utf-8") as f:
                json.dump({"ok": True}, f)
            self._html(200, "Fanvue connected! Tokens saved. Return to the terminal.")
            print("TOKENS_SAVED", flush=True)
        except Exception as exc:
            detail = ""
            if hasattr(exc, "response") and exc.response is not None:
                detail = exc.response.text[:400]
            with open(DONE_FILE, "w", encoding="utf-8") as f:
                json.dump({"ok": False, "error": str(exc), "detail": detail}, f)
            self._html(500, f"Token exchange failed: {exc}<br>{detail}")
            print(f"EXCHANGE_FAILED: {exc} {detail}", flush=True)

    def _html(self, status, msg):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if os.path.exists(DONE_FILE):
        os.remove(DONE_FILE)
    print("Callback+exchange server listening on :8000", flush=True)
    HTTPServer(("127.0.0.1", 8000), H).serve_forever()
