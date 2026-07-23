"""Fan pushback — AI/bot complaints, flattery skepticism, vision corrections."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

_AI_COMPLAINT = re.compile(
    r"(?i)\b("
    r"ai\s+feature|using\s+(the\s+)?ai|automated\s+chat|"
    r"not\s+(a\s+)?real\s+person|talk\s+to\s+(a\s+)?real|"
    r"you'?re\s+(a\s+)?bot|this\s+is\s+a\s+bot|"
    r"stop\s+using\s+(the\s+)?ai|fake\s+chat|"
    r"turn\s+off\s+the\s+robot|stop\s+the\s+robot|"
    r"robot|chatbot|not\s+automated|automated"
    r")\b"
)

_FLATTERY_SKEPTIC = re.compile(
    r"(?i)\b("
    r"tell\s+all\s+the\s+(boys|guys)|"
    r"say\s+that\s+to\s+(everyone|all)|"
    r"you\s+say\s+that\s+to|"
    r"what\s+you\s+tell\s+(everyone|all)|"
    r"generic\s+compliment|scripted|"
    r"copy\s+paste|same\s+line"
    r")\b"
)

_VISION_CORRECTION = re.compile(
    r"(?i)\b("
    r"neither\s+pic|no\s+sunglasses|not\s+in\s+sunglasses|"
    r"don'?t\s+have\s+sunglasses|without\s+sunglasses|"
    r"that'?s\s+not\s+(me|my)|wrong\s+pic|can'?t\s+see\s+it|"
    r"not\s+wearing\s+sunglasses|no\s+glasses"
    r")\b"
)

_SUNGLASSES_IN_REPLY = re.compile(
    r"(?i)\b("
    r"sunglasses|without\s+(the\s+)?sunglasses|"
    r"no\s+hiding\s+behind\s+sunglasses|take\s+(them\s+)?off"
    r")\b"
)


def is_ai_complaint(text: str) -> bool:
    return bool(_AI_COMPLAINT.search(text or ""))


def is_flattery_skeptic(text: str) -> bool:
    return bool(_FLATTERY_SKEPTIC.search(text or ""))


def is_vision_correction(text: str) -> bool:
    return bool(_VISION_CORRECTION.search(text or ""))


def fan_has_pushback(text: str) -> bool:
    low = text or ""
    return (
        is_ai_complaint(low)
        or is_flattery_skeptic(low)
        or is_vision_correction(low)
    )


_SEXUAL_HEAT = re.compile(
    r"(?i)\b("
    r"sports\s+bra|lingerie|wondering\s+what\s+you'?d\s+do|"
    r"next\s+to\s+me|in\s+bed|touching\s+myself|getting\s+me\s+wet|"
    r"horny|so\s+hard|so\s+wet|naked|nude|pussy|cock|dick|"
    r"fuck(?:ing)?|cum|stroke|jerk\s+off|turn(?:s|ed)?\s+on|"
    r"😈|🍆|💦"
    r")\b"
)


def is_sexual_heat_reply(text: str) -> bool:
    return bool(_SEXUAL_HEAT.search(text or ""))


def pushback_in_turns(
    turns: Optional[List[Dict[str, Any]]],
    *,
    lookback: int = 10,
) -> bool:
    """Recent fan messages called us out — stays hot even if this turn is short."""
    if not turns:
        return False
    seen = 0
    for turn in reversed(turns):
        if (turn.get("role") or "") != "user":
            continue
        seen += 1
        if fan_has_pushback(str(turn.get("content") or "")):
            return True
        if seen >= lookback:
            break
    return False


def thread_in_pushback_mode(
    fan_message: str,
    turns: Optional[List[Dict[str, Any]]],
    mem: Optional[dict],
) -> bool:
    """No heat / flirt / sell pressure — fan is skeptical or thinks we're a bot."""
    mem = mem or {}
    if mem.get("pushback_active"):
        return True
    if fan_has_pushback(fan_message or ""):
        return True
    return pushback_in_turns(turns)


def vision_mentions_sunglasses(description: str) -> bool:
    return bool(re.search(r"(?i)\bsunglasses\b", description or ""))


def reply_invents_sunglasses(reply: str, vision_desc: str = "") -> bool:
    if not _SUNGLASSES_IN_REPLY.search(reply or ""):
        return False
    return not vision_mentions_sunglasses(vision_desc)


def pushback_turn_block(fan_message: str) -> str:
    lines = [
        "FAN PUSHBACK — CRITICAL (he is calling you out; obey this over ACTIVE MOVE):",
        "- Acknowledge what he said in plain human words. No deflection.",
        "- Do NOT ask for another photo this turn. Do NOT invent details (sunglasses, etc.).",
        "- Do NOT use generic validation ('you're different', 'got me soft', 'only you').",
    ]
    if is_ai_complaint(fan_message):
        lines.append(
            "- He thinks this feels automated — reassure you're real: one specific, "
            "casual detail (not a sales line). Invite normal chat."
        )
    if is_flattery_skeptic(fan_message):
        lines.append(
            "- He teased that you flatter everyone — play along with humor, "
            "one concrete thing you noticed about HIM (from chat/photo), not a stamp."
        )
    if is_vision_correction(fan_message):
        lines.append(
            "- He corrected your photo read — own the miss lightly, trust HIS description, "
            "react to what's actually in his pic per vision block."
        )
    return "\n".join(lines)


_PUSHBACK_FALLBACKS = (
    "lol fair… you caught me. i'm right here though — talk to me for real",
    "haha ok you pay attention… i like that. what made you say that?",
    "you're not wrong to call me out — i'm listening. what's on your mind?",
    "mm touché… alright, no script. tell me what you're actually thinking",
)

_AI_FALLBACKS = (
    "lol it's just me on my phone… no bots. what's up with you rn?",
    "haha i'm real, promise — just typing fast. talk to me?",
    "fair — it's me, not a robot. what do you wanna know?",
)

_SKEPTIC_FALLBACKS = (
    "haha maybe… but you did send me that pic and i noticed",
    "lol guilty of flirting but you're the one who called my ass everything",
    "ok fair — prove me wrong then, keep talking like that",
)


def pick_pushback_fallback(fan_message: str, *, banned: set[str] | None = None) -> str:
    banned = banned or set()
    if is_ai_complaint(fan_message):
        pool = _AI_FALLBACKS
    elif is_flattery_skeptic(fan_message):
        pool = _SKEPTIC_FALLBACKS
    else:
        pool = _PUSHBACK_FALLBACKS
    for line in pool:
        norm = re.sub(r"\s+", " ", (line or "").lower().strip())
        if norm not in banned:
            return line
    return pool[0]
