"""
New-subscriber welcome.

Two paths:
  1) Fan writes first → router/phase_hook (handled elsewhere).
  2) Poll subscribers; ~15 min after firstSubscribedAt, if they still haven't
     been welcomed and haven't opened a real chat, send a soft opener.
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from config import config
from core import fan_memory

WELCOME_ENABLED = os.getenv("WELCOME_ENABLED", "1") == "1"
WELCOME_AFTER_MINUTES = int(os.getenv("WELCOME_AFTER_SUBSCRIBE_MINUTES", "15"))
WELCOME_WINDOW_MAX_MINUTES = int(os.getenv("WELCOME_WINDOW_MAX_MINUTES", "50"))
WELCOME_MAX_PER_PASS = int(os.getenv("WELCOME_MAX_PER_PASS", "2"))

_TEMPLATES_EN = [
    "so glad you subscribed, now we can finally talkk 😋",
    "hey… so glad you're here. now we can actually talk 😋",
    "mmm finally — glad you subscribed. talk to me 👀",
    "hi… been waiting for you to sub. now we can chat properly 😋",
]

_TEMPLATES_ES = [
    "qué bien que te hayas suscrito, ahora sí podemos hablar 😋",
    "hey… me alegra que estés aquí. ahora sí podemos hablar de verdad 😋",
    "mmm por fin — qué bien que te hayas suscrito. háblame 👀",
]


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def pick_welcome_text(*, spanish: bool = False) -> str:
    pool = _TEMPLATES_ES if spanish else _TEMPLATES_EN
    return random.choice(pool)


def _fan_has_real_chat(messages: list, fan_uuid: str) -> bool:
    """True if the fan already sent a non-automated message."""
    for m in messages or []:
        sender = m.get("sender") or {}
        sid = sender.get("uuid") if isinstance(sender, dict) else None
        if sid != fan_uuid:
            continue
        mtype = (m.get("type") or "").upper()
        if mtype.startswith("AUTOMATED"):
            continue
        text = (m.get("text") or "").strip()
        has_media = bool(m.get("hasMedia") or m.get("mediaUuids"))
        # Opaque gifts / tips / real text all count as them opening
        if text or has_media or mtype in ("TIP", "SINGLE_RECIPIENT"):
            return True
    return False


def _already_welcomed_by_us(messages: list, creator_uuid: str) -> bool:
    for m in messages or []:
        sender = m.get("sender") or {}
        sid = sender.get("uuid") if isinstance(sender, dict) else None
        if sid != creator_uuid:
            continue
        text = (m.get("text") or "").lower()
        if any(
            k in text
            for k in (
                "glad you subscribed",
                "finally talk",
                "te hayas suscrito",
                "podemos hablar",
                "been waiting for you to sub",
            )
        ):
            return True
    return False


def run_pass(fv, creator_uuid: str) -> int:
    """Send delayed welcome DMs to fresh subscribers. Returns count sent."""
    if not WELCOME_ENABLED or not creator_uuid:
        return 0
    now = datetime.now(timezone.utc)
    lo = timedelta(minutes=WELCOME_AFTER_MINUTES)
    hi = timedelta(minutes=max(WELCOME_AFTER_MINUTES + 1, WELCOME_WINDOW_MAX_MINUTES))
    sent = 0
    try:
        subs = fv.list_subscribers(creator_uuid, size=50)
    except Exception as exc:
        print(f"   welcome: list_subscribers failed: {exc}")
        return 0

    for sub in subs:
        if sent >= WELCOME_MAX_PER_PASS:
            break
        fan_uuid = sub.get("uuid")
        handle = sub.get("handle") or "fan"
        if not fan_uuid or fan_uuid == creator_uuid:
            continue
        sub_info = sub.get("subscription") or {}
        if (sub_info.get("status") or "").lower() not in ("active", "pending_confirmation", ""):
            # still allow pending; skip cancelled
            if (sub_info.get("status") or "").lower() in ("cancelled", "paused"):
                continue
        first_at = _parse_iso(sub.get("firstSubscribedAt")) or _parse_iso(
            sub_info.get("currentPeriodStart")
        )
        if not first_at:
            continue
        age = now - first_at
        if age < lo or age > hi:
            continue

        mem = fan_memory.get(fan_uuid) or {}
        if mem.get("welcome_sent_at"):
            continue
        if int(mem.get("messages") or 0) > 0:
            # They already chatted — first-message path owns welcome
            fan_memory.mark_welcome_sent(fan_uuid, fan_handle=handle, kind="skipped_chatted")
            continue

        try:
            messages = fv.get_messages(fan_uuid, size=10)
        except Exception:
            # Chat may not exist yet — try create + send
            messages = []

        if _fan_has_real_chat(messages, fan_uuid):
            fan_memory.mark_welcome_sent(fan_uuid, fan_handle=handle, kind="skipped_chatted")
            continue
        if _already_welcomed_by_us(messages, creator_uuid):
            fan_memory.mark_welcome_sent(fan_uuid, fan_handle=handle, kind="already_in_chat")
            continue

        text = pick_welcome_text(spanish=False)
        try:
            fv.ensure_chat(creator_uuid, fan_uuid)
            fv.send_message(fan_uuid, text)
        except Exception as exc:
            print(f"   welcome: send @{handle} failed: {exc}")
            continue

        fan_memory.mark_welcome_sent(fan_uuid, fan_handle=handle, kind="subscribe_delay")
        print(f"   👋 welcome @{handle} (sub ~{int(age.total_seconds() // 60)}m ago): {text}")
        sent += 1

    return sent
