"""Detect when a fan closed the chat — block re-engagement harassment."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

# Fan explicitly leaving / pausing — not mid-flirt silence.
_FAN_FAREWELL = re.compile(
    r"(?i)\b("
    r"good\s*night|gn\b|bye\b|see\s+(you|ya)|talk\s+(later|soon|tomorrow)|ttyl|gtg|"
    r"going\s+to\s+(bed|sleep|work)|heading\s+to\s+work|off\s+to\s+work|"
    r"get(?:ting)?\s+ready\s+for\s+work|have\s+to\s+get\s+ready|"
    r"gotta\s+go|got\s+to\s+go|need\s+to\s+go|have\s+to\s+go|"
    r"have\s+to\s+run|gotta\s+run|need\s+to\s+run|"
    r"(?:i'?m|im)\s+(?:off|out|leaving|done)\b|"
    r"catch\s+you\s+(later|soon)|speak\s+(later|soon)|"
    r"sleep\s+well|sweet\s+dreams|logging\s+off|"
    r"adi[oó]s|buenas\s+noches|hasta\s+(ma[nñ]ana|luego|pronto)|me\s+voy|"
    r"nos\s+vemos|descansa|dulces\s+sue[nñ]os|a\s+dormir|chao|"
    r"cu[ií]date|te\s+cuidas|voy\s+al\s+trabajo|me\s+voy\s+a\s+trabajar"
    r")\b"
)

# "have to X" where X is leave/work/sleep (Tommy: "have to get ready for work")
_FAN_HAVE_TO_LEAVE = re.compile(
    r"(?i)\b("
    r"have\s+to\s+.{0,28}(work|go|run|leave|sleep|bed|shift)|"
    r"got\s+to\s+.{0,28}(work|go|run|leave|sleep|bed|shift)|"
    r"need\s+to\s+.{0,28}(work|go|run|leave|sleep|bed|shift)"
    r")\b"
)

_CREATOR_SOFT_CLOSE = re.compile(
    r"(?i)\b("
    r"come\s+(find|back)|when\s+you'?re\s+free|i'?ll\s+be\s+(here|right\s+here)|"
    r"talk\s+(later|soon)|catch\s+you|see\s+you\s+(later|soon)|"
    r"have\s+a\s+good\s+(night|one)|good\s+luck\s+(at\s+work|today)|"
    r"cuando\s+puedas|hasta\s+luego|descansa"
    r")\b"
)

CLOSED_COOLDOWN_HOURS = 18


def fan_text_is_farewell(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_FAN_FAREWELL.search(t) or _FAN_HAVE_TO_LEAVE.search(t))


def _sender_uuid(msg: dict) -> Optional[str]:
    sender = msg.get("sender")
    if isinstance(sender, dict):
        return sender.get("uuid")
    if isinstance(sender, str):
        return sender
    return None


def fan_closed_in_messages(
    messages: List[dict],
    fan_uuid: str,
    *,
    lookback: int = 14,
) -> Tuple[bool, str]:
    """
    True if a recent fan message was a goodbye / leaving-for-work close.
    Returns (closed, reason).
    """
    seen = 0
    for msg in messages:
        if _sender_uuid(msg) != fan_uuid:
            continue
        text = (msg.get("text") or "").strip()
        if not text:
            continue
        seen += 1
        if fan_text_is_farewell(text):
            return True, text[:80]
        if seen >= lookback:
            break
    return False, ""


def creator_soft_closed(messages: List[dict], creator_uuid: str) -> bool:
    """Emma already sent a warm 'come back later' after his goodbye."""
    for msg in messages[:6]:
        if _sender_uuid(msg) != creator_uuid:
            continue
        text = (msg.get("text") or "").strip()
        if text and _CREATOR_SOFT_CLOSE.search(text):
            return True
    return False


def conversation_closed(
    messages: List[dict],
    fan_uuid: str,
    creator_uuid: str,
    mem: Optional[dict],
) -> bool:
    """Hard stop for mid-flow nudges — fan said bye / left for work."""
    mem = mem or {}
    closed_at = mem.get("conversation_closed_at")
    if closed_at and str(closed_at).strip():
        try:
            ts = datetime.fromisoformat(str(closed_at).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - ts < timedelta(hours=CLOSED_COOLDOWN_HOURS):
                return True
        except ValueError:
            pass

    fan_left, _ = fan_closed_in_messages(messages, fan_uuid)
    if not fan_left:
        return False

    # Fan said bye — closed even if we already replied warmly
    if creator_soft_closed(messages, creator_uuid):
        return True
    # Fan farewell without our close line yet — still closed
    return True


def mark_conversation_closed(
    fan_uuid: str,
    *,
    fan_handle: str = "",
    reason: str = "",
) -> None:
    from core import fan_memory

    if not fan_uuid:
        return
    try:
        fan_memory.patch_fanvue_platform(
            fan_uuid,
            {
                "conversation_closed_at": datetime.now(timezone.utc).isoformat(),
                "conversation_closed_reason": (reason or "farewell")[:120],
            },
            fan_handle=fan_handle,
        )
    except Exception:
        pass


def clear_conversation_closed(fan_uuid: str, *, fan_handle: str = "") -> None:
    from core import fan_memory

    if not fan_uuid:
        return
    try:
        fan_memory.patch_fanvue_platform(
            fan_uuid,
            {
                "conversation_closed_at": "",
                "conversation_closed_reason": "",
            },
            fan_handle=fan_handle,
        )
    except Exception:
        pass
