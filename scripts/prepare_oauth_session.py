"""Prepare OAuth session using the active Cloudflare tunnel URL."""
import json
import os
import secrets
import sys
from urllib.parse import urlencode

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_ROOT)
sys.path.insert(0, _ROOT)

from api.fanvue_oauth import clear_pending_oauth, generate_pkce, save_pending_oauth
from config import config

REDIRECT = sys.argv[1] if len(sys.argv) > 1 else None
if not REDIRECT:
    print("Usage: prepare_oauth_session.py <redirect_uri>")
    sys.exit(1)

pkce = generate_pkce()
state = secrets.token_hex(16)
clear_pending_oauth()
save_pending_oauth(state, pkce["code_verifier"])

session = {
    "redirect_uri": REDIRECT,
    "state": state,
    "code_verifier": pkce["code_verifier"],
}
with open(".oauth_tunnel_session.json", "w", encoding="utf-8") as f:
    json.dump(session, f, indent=2)

params = {
    "client_id": config.FANVUE_CLIENT_ID,
    "redirect_uri": REDIRECT,
    "response_type": "code",
    "scope": config.FANVUE_OAUTH_SCOPES,
    "state": state,
    "code_challenge": pkce["code_challenge"],
    "code_challenge_method": "S256",
}
auth_url = f"{config.FANVUE_AUTH_URL}?{urlencode(params)}"
with open(".oauth_auth_url.txt", "w", encoding="utf-8") as f:
    f.write(auth_url)

print(REDIRECT)
print(auth_url)
