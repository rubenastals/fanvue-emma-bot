"""
Live chat heat score (0–100) for re-engagement timing and telemetry.

Used when a fan goes quiet: hotter threads get nudged sooner, especially
after visto (isRead) or a recent emoji reaction on Sophia's message.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

_HEAT_WORDS = re.compile(
    r"(?i)\b("
    r"hard|horny|wet|cock|dick|pussy|fuck|cum|stroke|jerk|"
    r"duro|caliente|mojada|polla|follar|correr|"
    r"besos|folla|xxx|desnuda|touch|kiss|babe|bebe|mi vida|"
    r"te quiero|te deseo|harder|m[aá]s duro|mandala|dale|unlock|"
    r"ass|tits|boobs|nude|naked|sexy|hot\b"
    r")\b"
)

_COMPLIMENT = re.compile(
    r"(?i)\b("
    r"pretty|beautiful|sexy|hot|gorgeous|stunning|cute|handsome|"
    r"look\s+amazing|you'?re\s+(so\s+)?(hot|sexy|pretty|gorgeous)"
    r")\b"
)

_HOT_THRESHOLD = 40
_WARM_THRESHOLD = 25


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _sender_uuid(msg: dict) -> Optional[str]:
    sender = msg.get("sender")
    if isinstance(sender, dict):
        return sender.get("uuid")
    if isinstance(sender, str):
        return sender
    return None


def chat_heat_score(
    messages: List[dict],
    fan_uuid: str,
    mem: Optional[dict],
    *,
    creator_uuid: str = "",
    is_read: bool = False,
) -> int:
    """
    0–100 score: how hot/engaged this thread is right now.
    Higher → nudge sooner after silence / visto.
    """
    mem = mem or {}
    score = 0

    status = (mem.get("status") or "").lower()
    if status in ("spender", "whale"):
        score += 28
    elif status == "warm":
        score += 12

    if float(mem.get("total_spent") or 0) > 0:
        score += 10

    fan_hits = 0
    compliment_hits = 0
    media_hits = 0
    checked = 0
    for msg in messages[:12]:
        if _sender_uuid(msg) != fan_uuid:
            continue
        text = (msg.get("text") or "").strip()
        if msg.get("hasMedia") or msg.get("mediaUuids"):
            media_hits += 1
        if text:
            checked += 1
            if _HEAT_WORDS.search(text):
                fan_hits += 1
            if _COMPLIMENT.search(text):
                compliment_hits += 1
        if checked >= 5:
            break

    score += min(35, fan_hits * 14)
    score += min(12, compliment_hits * 8)
    if media_hits:
        score += min(15, media_hits * 8)

    msgs = int(mem.get("messages") or 0)
    if msgs >= 12:
        score += 8
    elif msgs >= 6:
        score += 4

    recent_tech = [str(t).upper() for t in (mem.get("recent_techniques") or []) if t]
    if any("HEAT" in t for t in recent_tech[-3:]):
        score += 10

    if is_read:
        score += 12

    react_at = _parse_iso(mem.get("last_fan_reaction_at"))
    if react_at and datetime.now(timezone.utc) - react_at < timedelta(hours=6):
        score += 18

    if mem.get("last_fan_image_at"):
        img_at = _parse_iso(mem.get("last_fan_image_at"))
        if img_at and datetime.now(timezone.utc) - img_at < timedelta(hours=24):
            score += 8

    return max(0, min(100, score))


def is_hot_score(score: int, *, threshold: int = _HOT_THRESHOLD) -> bool:
    return int(score) >= threshold


def is_warm_score(score: int, *, threshold: int = _WARM_THRESHOLD) -> bool:
    return int(score) >= threshold


def heat_label(score: int) -> str:
    if score >= 70:
        return "BLAZING"
    if score >= _HOT_THRESHOLD:
        return "HOT"
    if score >= _WARM_THRESHOLD:
        return "WARM"
    return "COLD"


def explicit_horny_now(fan_message: str) -> bool:
    """Graphic horny content THIS message (not just warm banter)."""
    from core.turn_policy import _HORNY

    return bool(re.search(_HORNY, (fan_message or "").lower()))


def _thread_horny(
    fan_message: str,
    history_turns: Optional[List[dict]] = None,
    *,
    facts: Any = None,
) -> bool:
    from core.turn_policy import _HORNY

    horny = bool(getattr(facts, "horny", False) if facts is not None else False)
    if not horny:
        horny = explicit_horny_now(fan_message or "")
    if not horny:
        horny = bool(_HEAT_WORDS.search(fan_message or ""))
    if not horny and history_turns:
        for turn in history_turns[-6:]:
            if turn.get("role") != "user":
                continue
            body = (turn.get("content") or "").strip()
            if re.search(_HORNY, body.lower()) or _HEAT_WORDS.search(body):
                horny = True
                break
    return horny


def heat_close_eligible(
    mem: dict,
    fan_message: str,
    *,
    facts: Any = None,
    history_turns: Optional[List[dict]] = None,
    unpaid: bool = False,
    sell_paused: bool = False,  # deprecated — sell_gate.chill_turn owns pauses
) -> bool:
    """
    Hot explicit thread → natural moment to attach a cheap PPV (not bond-only gasp).

    Code may attach; prompt must tease the lock after matching his RP.
    """
    if unpaid:
        return False
    mem = mem or {}
    if mem.get("fan_boundary_active") or mem.get("photo_refusal_active"):
        return False
    try:
        from core.fan_pushback import is_fan_boundary

        if is_fan_boundary(fan_message or ""):
            return False
    except Exception:
        pass

    msgs = int(mem.get("messages") or 0)
    if msgs < 6:
        return False

    return _thread_horny(fan_message, history_turns, facts=facts)


def hot_unpaid_nudge_eligible(
    mem: dict,
    fan_message: str,
    *,
    facts: Any = None,
    history_turns: Optional[List[dict]] = None,
    sell_paused: bool = False,  # deprecated
) -> bool:
    """Unpaid lock exists but thread is hot — filthy unlock nudge, not bond-only."""
    if int((mem or {}).get("messages") or 0) < 6:
        return False
    return _thread_horny(fan_message, history_turns, facts=facts)


def active_window_minutes(score: int) -> int:
    """How long after fan's last msg we skip re-engagement."""
    if score >= 70:
        return 8
    if score >= _HOT_THRESHOLD:
        return 12
    if score >= _WARM_THRESHOLD:
        return 18
    return 25
