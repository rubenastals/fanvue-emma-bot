"""
Receive-only Fanvue webhook listener (no Celery, no DB, no Fanvue API).

Use this to verify Fanvue can reach your machine while the API is down.
Logs every POST to console and always returns 200 (unless signature fails
and FANVUE_WEBHOOK_SECRET is set).

  python scripts/webhook_listen.py
  # then in another terminal: cloudflared tunnel --url http://127.0.0.1:8000
"""
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from fastapi import FastAPI, HTTPException, Request
import uvicorn

from config import config

app = FastAPI(title="Emma webhook listen (receive-only)")
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webhook_inbox")
os.makedirs(LOG_DIR, exist_ok=True)


def _verify(raw: bytes, header: str) -> None:
    secret = config.FANVUE_WEBHOOK_SECRET
    if not secret:
        return
    if not header:
        raise HTTPException(401, "Missing X-Fanvue-Signature")
    ts = sig = None
    for part in header.split(","):
        k, _, v = part.partition("=")
        if k == "t":
            ts = v
        elif k == "v0":
            sig = v
    if not ts or not sig:
        raise HTTPException(401, "Malformed signature")
    if abs(int(time.time()) - int(ts)) > 300:
        raise HTTPException(401, "Stale timestamp")
    expected = hmac.new(
        secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise HTTPException(401, "Invalid signature")


def _save_and_print(kind: str, headers: dict, body: dict, raw: bytes) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(LOG_DIR, f"{stamp}_{kind}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"headers": headers, "body": body}, f, indent=2, ensure_ascii=False)
    print("\n" + "=" * 60)
    print(f"[{stamp}] {kind}  saved → {path}")
    print(f"type={body.get('type')!r}")
    print(json.dumps(body, indent=2, ensure_ascii=False)[:2000])
    print("=" * 60 + "\n")
    return path


@app.get("/health")
async def health():
    return {
        "status": "listening",
        "mode": "receive-only",
        "signature_required": bool(config.FANVUE_WEBHOOK_SECRET),
    }


@app.post("/webhook/fanvue")
@app.post("/webhook/fanvue/purchase")
@app.post("/webhooks/fanvue")
async def receive(request: Request):
    raw = await request.body()
    _verify(raw, request.headers.get("X-Fanvue-Signature", ""))
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        body = {"_raw": raw.decode("utf-8", errors="replace")}
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() in ("content-type", "x-fanvue-signature", "user-agent", "webhook-id")
    }
    path = _save_and_print(request.url.path.strip("/").replace("/", "_"), headers, body, raw)
    return {"status": "received", "saved": path}


if __name__ == "__main__":
    print("Emma webhook listen (receive-only)")
    print("  POST /webhook/fanvue")
    print("  GET  /health")
    print("  Logs →", LOG_DIR)
    if not config.FANVUE_WEBHOOK_SECRET:
        print("  WARN: FANVUE_WEBHOOK_SECRET empty → signatures NOT verified (ok for first Test)")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
