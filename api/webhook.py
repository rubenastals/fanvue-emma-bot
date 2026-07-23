import hashlib
import hmac
import json
import secrets
import time

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from config import config
from api.fanvue_oauth import (
    build_authorization_url,
    clear_pending_oauth,
    exchange_code_for_tokens,
    generate_pkce,
    load_tokens,
    save_pending_oauth,
)

app = FastAPI(title="Emma AI - Fanvue Bot")

_db = None
_celery_tasks = None


def get_db():
    global _db
    if _db is None:
        from database.db_manager import DBManager
        _db = DBManager()
    return _db


def get_celery_tasks():
    global _celery_tasks
    if _celery_tasks is None:
        from tasks import handle_incoming_message
        _celery_tasks = handle_incoming_message
    return _celery_tasks


def _verify_signature(raw_body: bytes, signature_header: str):
    """
    Fanvue Standard-Webhooks format: X-Fanvue-Signature: t=<ts>,v0=<hex>
    Signed payload = "{timestamp}.{raw_body}"
    """
    secret = config.FANVUE_WEBHOOK_SECRET
    if not secret:
        return

    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing signature header")

    timestamp = None
    signature = None
    for part in signature_header.split(","):
        key, _, value = part.partition("=")
        if key == "t":
            timestamp = value
        elif key == "v0":
            signature = value

    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="Malformed signature header")

    if abs(int(time.time()) - int(timestamp)) > 300:
        raise HTTPException(status_code=401, detail="Stale webhook timestamp")

    signed_payload = f"{timestamp}.".encode("utf-8") + raw_body
    expected = hmac.new(
        secret.encode("utf-8"), signed_payload, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")


def _parse_message_webhook(data: dict) -> tuple:
    """
    Returns (fan_uuid, message_uuid, message_text_or_none).

    Supports:
      - creator.message.received (Standard-Webhooks; metadata only, no text)
      - legacy flat test payloads {fanvue_id, message}
    """
    event_type = data.get("type")

    if event_type == "creator.message.received":
        payload = data.get("data", {})
        if payload.get("sender") != "fan":
            return None, None, None
        fan_uuid = payload.get("fan", {}).get("uuid")
        message_uuid = payload.get("uuid")
        return fan_uuid, message_uuid, None

    # Legacy / manual test format
    fan_uuid = data.get("fanvue_id") or data.get("sender", {}).get("uuid")
    message_text = data.get("message") or data.get("text")
    if fan_uuid and message_text:
        return fan_uuid, None, message_text

    return None, None, None


# ──────────────── OAuth routes ────────────────

@app.get("/oauth/login")
async def oauth_login():
    """Start Fanvue OAuth — redirects browser to Fanvue authorization."""
    pkce = generate_pkce()
    state = secrets.token_hex(16)
    save_pending_oauth(state, pkce["code_verifier"])
    url = build_authorization_url(state, pkce["code_challenge"])
    return RedirectResponse(url)


@app.get("/oauth/callback")
async def oauth_callback(code: str = None, state: str = None, error: str = None):
    if error:
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state")

    from api.fanvue_oauth import load_pending_oauth

    pending = load_pending_oauth()
    if not pending or pending.get("state") != state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    try:
        exchange_code_for_tokens(code, pending["code_verifier"])
        clear_pending_oauth()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return HTMLResponse(
        "<h2>Fanvue connected!</h2><p>Tokens saved. You can close this tab.</p>"
    )


@app.get("/oauth/status")
async def oauth_status():
    tokens = load_tokens()
    return {
        "connected": bool(tokens),
        "expires_at": tokens.get("expires_at") if tokens else None,
        "scope": tokens.get("scope") if tokens else None,
    }


# ──────────────── Webhooks ────────────────

@app.post("/webhook/fanvue")
async def fanvue_webhook(request: Request):
    """
    Receives Fanvue webhook events (creator.message.received).
    Metadata-only events trigger a chat API fetch for the message text.
    """
    try:
        raw = await request.body()
        _verify_signature(raw, request.headers.get("X-Fanvue-Signature", ""))

        data = json.loads(raw)
        event_type = data.get("type")

        if event_type == "creator.message.reaction":
            from core.fan_memory import record_fan_reaction
            from core.webhook_events import parse_message_reaction

            fan_uuid, emoji, msg_uuid = parse_message_reaction(data)
            if fan_uuid and emoji:
                record_fan_reaction(
                    fan_uuid,
                    emoji=emoji,
                    message_uuid=msg_uuid,
                    actor_uuid=fan_uuid,
                )
            return {"status": "reaction_recorded", "fan_uuid": fan_uuid}

        fan_uuid, message_uuid, message_text = _parse_message_webhook(data)

        if not fan_uuid:
            return {"status": "ignored", "reason": "not a fan message event"}

        if not message_text and message_uuid:
            from api.fanvue_connector import FanvueConnector
            fv = FanvueConnector()
            message_text = fv.fetch_message_text(fan_uuid, message_uuid)

        if not message_text:
            return {"status": "ignored", "reason": "empty message"}

        task_fn = get_celery_tasks()
        task = task_fn.delay(fan_uuid, message_text)
        return {"status": "queued", "task_id": task.id, "fan_uuid": fan_uuid}

    except HTTPException:
        raise
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/fanvue/purchase")
async def fanvue_purchase_webhook(request: Request):
    """Handles creator.payment.succeeded (PPV purchase)."""
    try:
        raw = await request.body()
        _verify_signature(raw, request.headers.get("X-Fanvue-Signature", ""))

        data = json.loads(raw)
        event_type = data.get("type")

        fan_uuid = None
        amount = None

        if event_type == "creator.payment.succeeded":
            payload = data.get("data", {})
            fan_uuid = payload.get("fan", {}).get("uuid")
            gross = payload.get("gross")  # cents
            if gross is not None:
                amount = float(gross) / 100.0
        else:
            # Legacy test format
            fan_uuid = data.get("fanvue_id")
            amount = data.get("amount")

        if not fan_uuid or amount is None:
            raise HTTPException(status_code=400, detail="Missing fan or amount")

        updated = get_db().record_purchase(fan_uuid, float(amount))
        if not updated:
            raise HTTPException(status_code=404, detail="Client not found")

        return {"status": "ok"}

    except HTTPException:
        raise
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    return {"status": "Emma is online", "fanvue_connected": bool(load_tokens())}
