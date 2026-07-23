"""
New-account onboarding helpers — welcome backfill + repesca context.

Norm (see .cursor/rules/new-account-onboarding.mdc):
  1. Welcome unopened subs who never got an opener — **active membership only**.
  2. Expired/cancelled who already got a wrong welcome → churn apology (not re-welcome).
  3. Never spam live threads — read message history before any outbound.
  4. Repesca only when history says the silence is natural (not mid-argument / opt-out).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from core.welcome import (
    _fan_has_real_chat,
    pick_welcome_text,
    welcome_message_sent,
)

MembershipBucket = Literal["active_sub", "expired", "follower", "unknown"]

EXPIRED_STATUSES = frozenset({"expired", "cancelled", "inactive", "churned"})

_NEGATIVE_FAN = re.compile(
    r"(?i)\b(bot|robot|fake|scam|spam|stop texting|leave me alone|fuck off|block you)\b"
)
_OPT_OUT = re.compile(r"(?i)\b(don'?t message|no more messages|stop messaging|unsubscribe)\b")
_NUDGE_MARKERS = re.compile(
    r"(?i)\b(still there|you good|todo bien|segu[ií]s ah[ií]|went quiet|volv[eé]|appear)\b"
)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def _sender_uuid(msg: dict) -> Optional[str]:
    sender = msg.get("sender") or {}
    return sender.get("uuid") if isinstance(sender, dict) else None


def _msg_ts(msg: dict) -> Optional[datetime]:
    for key in ("createdAt", "sentAt", "timestamp"):
        ts = _parse_iso(msg.get(key))
        if ts:
            return ts
    return None


def classify_membership(
    insights: dict,
    *,
    in_active_sub_list: bool,
    subscription_status: str = "",
) -> MembershipBucket:
    """Map Fanvue insights + subscriber list to a welcome/repesca bucket."""
    status = (insights.get("status") or "").lower()
    sub_st = (subscription_status or "").lower()
    if sub_st in ("cancelled", "paused"):
        return "expired"
    if in_active_sub_list or status == "subscriber":
        return "active_sub"
    if status in EXPIRED_STATUSES:
        return "expired"
    if status == "follower":
        return "follower"
    if not in_active_sub_list and status and status != "subscriber":
        return "expired"
    return "unknown"


def thread_is_live(
    messages: list,
    fan_uuid: str,
    creator_uuid: str,
    *,
    active_within_minutes: int = 45,
    now: Optional[datetime] = None,
) -> bool:
    """
    True when the thread is still "hot" — skip cold welcome / extra nudges.

    Live if the fan messaged recently, spoke last, or there was back-and-forth
  in the last hour (even if we replied after).
    """
    if not messages:
        return False
    now = now or datetime.now(timezone.utc)
    window = timedelta(minutes=active_within_minutes)
    hour = timedelta(hours=1)

    newest = messages[0]
    if _sender_uuid(newest) == fan_uuid:
        return True

    fan_recent = creator_recent = False
    fan_in_hour = creator_in_hour = False
    for msg in messages[:16]:
        sid = _sender_uuid(msg)
        ts = _msg_ts(msg)
        if not ts:
            continue
        age = now - ts
        if sid == fan_uuid:
            if age < window:
                fan_recent = True
            if age < hour:
                fan_in_hour = True
        elif sid == creator_uuid:
            if age < window:
                creator_recent = True
            if age < hour:
                creator_in_hour = True

    if fan_recent:
        return True
    if fan_in_hour and creator_in_hour:
        return True
    return False


@dataclass(frozen=True)
class WelcomeDecision:
    fan_uuid: str
    handle: str
    action: Literal["welcome", "skip", "churn_fix"]
    membership: MembershipBucket
    reason: str
    text: str = ""
    source: str = ""


def evaluate_welcome(
    *,
    fan_uuid: str,
    handle: str,
    creator_uuid: str,
    messages: list,
    mem: dict,
    insights: dict,
    in_active_sub_list: bool,
    subscription_status: str = "",
    source: str = "",
) -> WelcomeDecision:
    """Decide welcome / skip / churn-fix from history + membership."""
    membership = classify_membership(
        insights,
        in_active_sub_list=in_active_sub_list,
        subscription_status=subscription_status,
    )
    base = dict(
        fan_uuid=fan_uuid,
        handle=handle,
        membership=membership,
        source=source,
    )

    if mem.get("welcome_sent_at") or welcome_message_sent(messages, creator_uuid):
        return WelcomeDecision(
            **base,
            action="skip",
            reason="already_welcomed",
        )

    if _fan_has_real_chat(messages, fan_uuid) or int(mem.get("messages") or 0) > 0:
        return WelcomeDecision(
            **base,
            action="skip",
            reason="fan_already_chatted",
        )

    if thread_is_live(messages, fan_uuid, creator_uuid):
        return WelcomeDecision(
            **base,
            action="skip",
            reason="thread_live",
        )

    if membership == "active_sub":
        return WelcomeDecision(
            **base,
            action="welcome",
            reason="active_unopened",
            text=pick_welcome_text(spanish=False),
        )

    if membership == "expired" and welcome_message_sent(messages, creator_uuid):
        return WelcomeDecision(
            **base,
            action="churn_fix",
            reason="expired_wrong_welcome",
        )

    if membership == "expired":
        return WelcomeDecision(
            **base,
            action="skip",
            reason="expired_no_welcome",
        )

    if membership == "follower":
        return WelcomeDecision(
            **base,
            action="skip",
            reason="follower_not_sub",
        )

    return WelcomeDecision(
        **base,
        action="skip",
        reason="unknown_membership",
    )


def repesca_appropriate(
    messages: list,
    fan_uuid: str,
    creator_uuid: str,
    mem: dict,
    *,
    now: Optional[datetime] = None,
) -> tuple[bool, str]:
    """
    History-aware gate before auto re-engage (repesca).

    Returns (ok, reason). Complements timing/heat gates in reengagement.py.
    """
    now = now or datetime.now(timezone.utc)
    if not messages:
        return False, "no_history"

    if not _fan_has_real_chat(messages, fan_uuid):
        return False, "fan_never_replied"

    if int(mem.get("messages") or 0) < 1:
        return False, "never_chatted"

    fan_texts: list[str] = []
    for msg in messages[:8]:
        if _sender_uuid(msg) == fan_uuid:
            t = (msg.get("text") or "").strip()
            if t:
                fan_texts.append(t)
    for text in fan_texts[:2]:
        if _NEGATIVE_FAN.search(text) or _OPT_OUT.search(text):
            return False, "fan_negative"

    if thread_is_live(messages, fan_uuid, creator_uuid, active_within_minutes=30, now=now):
        return False, "thread_live"

    # Last two creator bubbles = we already double-texted; don't nudge on top.
    creator_streak = 0
    for msg in messages[:4]:
        if _sender_uuid(msg) == creator_uuid:
            creator_streak += 1
        else:
            break
    if creator_streak >= 2:
        return False, "creator_double_text"

    newest = messages[0]
    if _sender_uuid(newest) == creator_uuid:
        body = (newest.get("text") or "").strip()
        if body and _NUDGE_MARKERS.search(body):
            return False, "already_nudged"

    return True, "ok"


def list_all_chats(fv) -> list[dict]:
    out: list[dict] = []
    for page in range(1, 21):
        data = fv._request("GET", "/chats", params={"size": 50, "page": page})
        batch = data.get("data", []) if isinstance(data, dict) else []
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 50:
            break
    return out


def active_subscriber_ids(fv, creator_uuid: str) -> set[str]:
    ids: set[str] = set()
    for page in range(1, 21):
        batch = fv.list_subscribers(creator_uuid, page=page, size=50)
        if not batch:
            break
        for sub in batch:
            uid = sub.get("uuid")
            if uid:
                ids.add(uid)
        if len(batch) < 50:
            break
    return ids
