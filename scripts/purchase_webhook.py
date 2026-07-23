"""
Fanvue PURCHASE webhook listener (no Postgres needed).

Handles creator.payment.succeeded (PPV unlock, tip) and, optionally,
sends an Emma thank-you message to the fan via the Fanvue API.

Run together with the tunnel:  python scripts/start_purchase_webhook.py
"""
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from fastapi import FastAPI, HTTPException, Request
import uvicorn

from config import config

app = FastAPI(title="Emma purchase webhook")
LOG_DIR = os.path.join(_ROOT, "webhook_inbox")
os.makedirs(LOG_DIR, exist_ok=True)

# Set to "1" in env to auto-send an Emma thank-you after each purchase
SEND_THANK_YOU = os.getenv("EMMA_THANK_YOU_ON_PURCHASE", "1") == "1"


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


def _extract_purchase(body: dict):
    """Return (fan_uuid, amount_usd, kind) or (None, None, None)."""
    etype = body.get("type", "")
    data = body.get("data", body)
    fan = data.get("fan") or data.get("sender") or data.get("user") or {}
    fan_uuid = fan.get("uuid") if isinstance(fan, dict) else None
    gross = data.get("gross") or data.get("amount") or data.get("price")
    amount = None
    if gross is not None:
        try:
            amount = float(gross) / 100.0 if float(gross) > 100 else float(gross)
        except (TypeError, ValueError):
            amount = None
    return fan_uuid, amount, etype


def _send_thank_you(fan_uuid: str, amount):
    """Generate + send a grateful Emma follow-up (best effort)."""
    try:
        from api.fanvue_connector import FanvueConnector
        from core.reply_engine import fanvue_messages_to_turns, split_into_messages
        from core.turn_policy import TurnDecision

        fv = FanvueConnector()
        me = fv.get_current_user()
        msgs = fv.get_messages(fan_uuid, size=40)
        turns = fanvue_messages_to_turns(msgs, fan_uuid, me.get("uuid"), max_messages=40)
        trigger = (
            f"[SYSTEM: The fan just PAID/unlocked your content (${amount}). "
            "Respond with genuine warmth and gratitude. Make him feel special. "
            "Do NOT upsell or mention another price right now.]"
        )
        # Force chill: reward, don't immediately pitch again
        chill = TurnDecision(
            mode="chill",
            reason="post-purchase thank-you",
            max_bubbles=2,
            allow_ppv_talk=False,
            allow_price=False,
        )
        if getattr(config, "REPLY_V2", False) and not getattr(
            config, "SIMPLE_PROMPT", True
        ):
            from core.intent_router import RouteResult
            from core.reply_v2 import generate_reply_v2
            from core.turn_facts import TurnFacts

            reply, _, _ = generate_reply_v2(
                trigger,
                history_turns=turns,
                fan_uuid=fan_uuid,
                route_result=RouteResult(
                    "reward_purchase",
                    chill,
                    TurnFacts(recent_purchase=True),
                    {"reward_purchase": True},
                ),
            )
        else:
            from core.reply_engine import generate_emma_reply

            reply, _ = generate_emma_reply(
                trigger, history_turns=turns, fan_uuid=fan_uuid, decision=chill
            )

        for b in split_into_messages(reply, max_bubbles=2):
            fv.send_message(fan_uuid, b)
            time.sleep(1.5)
        print(f"   💕 thank-you sent to {fan_uuid}")
    except Exception as e:
        print(f"   ⚠️ thank-you failed: {e}")


@app.get("/health")
async def health():
    return {"status": "listening", "thank_you": SEND_THANK_YOU}


@app.post("/webhook/fanvue/purchase")
@app.post("/webhook/fanvue")
@app.post("/webhooks/fanvue")
async def receive(request: Request):
    raw = await request.body()
    _verify(raw, request.headers.get("X-Fanvue-Signature", ""))
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        body = {"_raw": raw.decode("utf-8", errors="replace")}

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    with open(os.path.join(LOG_DIR, f"{stamp}_purchase.json"), "w", encoding="utf-8") as f:
        json.dump(body, f, indent=2, ensure_ascii=False)

    etype = body.get("type", "?")
    fan_uuid, amount, _ = _extract_purchase(body)
    print(f"\n💰 [{stamp}] event={etype} fan={fan_uuid} amount=${amount}")

    # Persist the purchase in per-fan memory (upgrades status to spender/whale)
    if etype in ("creator.payment.succeeded",) and fan_uuid and amount is not None:
        try:
            from core import fan_memory

            mem = fan_memory.record_purchase(fan_uuid, amount)
            print(f"   🧠 memory: spent=${mem.get('total_spent')} status={mem.get('status')}")
        except Exception as e:
            print(f"   ⚠️ memory update failed: {e}")
        try:
            from core import convo_log

            convo_log.log_offer_outcome(fan_uuid, "purchased", amount=amount)
        except Exception as e:
            print(f"   ⚠️ outcome log failed: {e}")

    if etype in ("creator.payment.succeeded",) and fan_uuid and SEND_THANK_YOU:
        _send_thank_you(fan_uuid, amount)

    if etype == "creator.message.reaction":
        try:
            from core.fan_memory import record_fan_reaction
            from core.webhook_events import parse_message_reaction

            react_fan, emoji, msg_uuid = parse_message_reaction(body)
            if react_fan and emoji:
                record_fan_reaction(
                    react_fan,
                    emoji=emoji,
                    message_uuid=msg_uuid,
                    actor_uuid=react_fan,
                )
                print(f"   ❤️ reaction stored: {emoji} from {react_fan[:8]}…")
        except Exception as e:
            print(f"   ⚠️ reaction store failed: {e}")

    return {"status": "ok"}


if __name__ == "__main__":
    print("Emma purchase webhook")
    print("  POST /webhook/fanvue/purchase")
    print("  GET  /health")
    if not config.FANVUE_WEBHOOK_SECRET:
        print("  WARN: FANVUE_WEBHOOK_SECRET empty → signature NOT verified (ok for first Test)")
    print(f"  Auto thank-you: {SEND_THANK_YOU}")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
