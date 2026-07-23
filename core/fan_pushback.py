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

_PHOTO_REFUSAL = re.compile(
    r"(?i)\b("
    r"keep\s+(myself\s+)?private|stay\s+private|like\s+to\s+keep\s+private|"
    r"private\s+on\s+the\s+internet|prefer\s+(to\s+)?stay\s+private|"
    r"don'?t\s+want\s+to\s+send\s+(a\s+)?(pic|photo|selfie)|"
    r"won'?t\s+send\s+(a\s+)?(pic|photo|selfie)|"
    r"stop\s+asking(\s+me)?(\s+for)?(\s+(pic|photo|selfie|picture)s?)?|"
    r"not\s+comfortable\s+(sending|sharing)\s+(a\s+)?(pic|photo|selfie)?|"
    r"no\s+pics?\s+(of\s+me|please)?|"
    r"mantener(me)?\s+privad|no\s+quiero\s+(mandar|enviar)\s+(foto|pic)|"
    r"prefiero\s+no\s+(mandar|enviar)|deja\s+de\s+pedir(\s+foto)?"
    r")\b"
)

_FAN_BOUNDARY = re.compile(
    r"(?i)\b("
    r"being\s+pushy|too\s+pushy|you'?re\s+pushy|"
    r"could\s+be\s+reported|might\s+report|"
    r"get\s+offended|offended\s+easily|"
    r"back\s+off|leave\s+me\s+alone|"
    r"uncomfortable|creepy|not\s+okay|not\s+ok\b|"
    r"please\s+stop|stop\s+it|"
    r"muy\s+insistente|me\s+molesta"
    r")\b"
)

_BOUNDARY_WARM = re.compile(
    r"(?i)\b("
    r"sorry|apolog|thank|sweet|cute|kind|forgive|"
    r"believe\s+you|notification|busy|working|laptop|"
    r"respect\s+yourself|glad|happy\s+you|"
    r"how\s+are\s+you|what\s+do\s+you\s+like|free\s+time|"
    r"private|mystery|just\s+chat"
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


def is_photo_refusal(text: str) -> bool:
    return bool(_PHOTO_REFUSAL.search(text or ""))


def is_fan_boundary(text: str) -> bool:
    """Fan set a boundary — privacy, pushy, upset, stop asking."""
    low = text or ""
    return is_photo_refusal(low) or bool(_FAN_BOUNDARY.search(low))


def is_fan_upset_boundary(text: str) -> bool:
    """Upset/pushy boundary only — not generic photo-refusal privacy."""
    return bool(_FAN_BOUNDARY.search(text or ""))


def is_boundary_warm_message(text: str) -> bool:
    """Fan cooling down / normal chat after friction — not a new boundary."""
    t = (text or "").strip()
    if not t or is_fan_upset_boundary(t) or is_photo_refusal(t):
        return False
    return bool(_BOUNDARY_WARM.search(t))


def boundary_reconciling(
    fan_message: str,
    mem: Optional[dict],
    *,
    min_streak: int = 2,
) -> bool:
    """Sticky boundary memory but fan is warm again — allow BOND/HEAT, not SOFT EXIT loop."""
    mem = mem or {}
    if not (mem.get("fan_boundary_active") or mem.get("photo_refusal_active")):
        return False
    if is_fan_upset_boundary(fan_message or "") or is_photo_refusal(fan_message or ""):
        return False
    if not is_boundary_warm_message(fan_message or ""):
        return False
    return int(mem.get("boundary_warm_streak") or 0) >= min_streak


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


def boundary_in_turns(
    turns: Optional[List[Dict[str, Any]]],
    *,
    lookback: int = 12,
) -> bool:
    if not turns:
        return False
    seen = 0
    for turn in reversed(turns):
        if (turn.get("role") or "") != "user":
            continue
        seen += 1
        if is_fan_boundary(str(turn.get("content") or "")):
            return True
        if seen >= lookback:
            break
    return False


def thread_in_boundary_mode(
    fan_message: str,
    turns: Optional[List[Dict[str, Any]]],
    mem: Optional[dict],
) -> bool:
    """Fan upset now — no sell/heat pressure. Photo-refusal alone is softer (see photo_refusal)."""
    mem = mem or {}
    if mem.get("fan_boundary_active"):
        return True
    if thread_in_pushback_mode(fan_message, turns, mem):
        return True
    if is_fan_boundary(fan_message or ""):
        return True
    return boundary_in_turns(turns)


def thread_in_strict_boundary_mode(
    fan_message: str,
    turns: Optional[List[Dict[str, Any]]],
    mem: Optional[dict],
) -> bool:
    """Upset boundary OR photo refusal sticky — block sell + ask-pic (not all flirt)."""
    mem = mem or {}
    if mem.get("photo_refusal_active"):
        return True
    return thread_in_boundary_mode(fan_message, turns, mem)


def photo_refusal_in_turns(
    turns: Optional[List[Dict[str, Any]]],
    *,
    lookback: int = 12,
) -> bool:
    if not turns:
        return False
    seen = 0
    for turn in reversed(turns):
        if (turn.get("role") or "") != "user":
            continue
        seen += 1
        if is_photo_refusal(str(turn.get("content") or "")):
            return True
        if seen >= lookback:
            break
    return False


def thread_in_photo_refusal_mode(
    fan_message: str,
    turns: Optional[List[Dict[str, Any]]],
    mem: Optional[dict],
) -> bool:
    """Fan declined to send his pic — no more ASK PIC / pressure."""
    mem = mem or {}
    if mem.get("photo_refusal_active"):
        return True
    if is_photo_refusal(fan_message or ""):
        return True
    return photo_refusal_in_turns(turns)


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


def reengage_blocked(mem: Optional[dict]) -> bool:
    """Hard stop for auto nudges — boundary/pushback/refusal still hot in fan_memory."""
    mem = mem or {}
    if mem.get("fan_boundary_active") or mem.get("photo_refusal_active"):
        return True
    if mem.get("pushback_active"):
        return True
    return False


def vision_mentions_sunglasses(description: str) -> bool:
    return bool(re.search(r"(?i)\bsunglasses\b", description or ""))


def reply_invents_sunglasses(reply: str, vision_desc: str = "") -> bool:
    if not _SUNGLASSES_IN_REPLY.search(reply or ""):
        return False
    return not vision_mentions_sunglasses(vision_desc)


def photo_refusal_turn_block() -> str:
    return boundary_turn_block()


def boundary_turn_block() -> str:
    return (
        "FAN BOUNDARY — CRITICAL (he's upset or said no pics; obey over ACTIVE MOVE):\n"
        "- Respect it. Do NOT ask for his pic/selfie/face. Do NOT send or pitch PPV.\n"
        "- Do NOT tease 'offended easily' or sexualize him being shy/private.\n"
        "- No $ prices, no 'open this photo', no heat. One warm bubble — acknowledge + "
        "light topic from what HE said (game, day, hobby)."
    )


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

_PHOTO_REFUSAL_FALLBACKS = (
    "okay fair… no pressure. what's on your mind?",
    "got it, we can keep it chill. tell me something about your day",
    "respect — i'm listening. what were you saying?",
    "fair enough… keep talking, i'm here",
)


def _last_fan_text(fan_message: str, turns: Optional[List[Dict[str, Any]]]) -> str:
    """Prefer coalesced fan_message; else newest user turn."""
    msg = (fan_message or "").strip()
    if msg:
        return msg
    for turn in reversed(turns or []):
        if (turn.get("role") or "") == "user":
            t = (turn.get("content") or "").strip()
            if t:
                return t
    return ""


def pick_boundary_fallback(
    fan_message: str,
    *,
    turns: Optional[List[Dict[str, Any]]] = None,
    banned: Optional[set[str]] = None,
) -> str:
    """
    Warm reply after boundary/refusal — must match what HE actually said.
    Never reuse game/hobby stamps from another fan thread.
    """
    banned = banned or set()
    text = _last_fan_text(fan_message, turns)
    low = text.lower()

    pools: tuple[str, ...]
    if re.search(
        r"(?i)\b(thank|thanks|sweet|cute|kind|nice of you|appreciate)\b",
        low,
    ):
        pools = (
            "aw you're sweet too 🙈",
            "haha thank you… you're making me smile",
            "that's cute of you honestly",
        )
    elif re.search(
        r"(?i)\b("
        r"free time|what do you like|hobbies|what do you do|"
        r"interests|outside of work|when you'?re not"
        r")\b",
        low,
    ):
        pools = (
            "honestly gym, music, and scrolling my phone too much lol… you?",
            "usually gym or just chilling at home… what about you?",
            "gym, cooking badly, and tiktok rabbit holes lol. your turn",
        )
    elif re.search(r"(?i)\b(how are you|how'?s it going|what'?s up|wyd)\b", low):
        pools = (
            "pretty good, lazy day lol… you?",
            "doing alright… what's up with you?",
        )
    else:
        pools = _PHOTO_REFUSAL_FALLBACKS

    for line in pools:
        norm = re.sub(r"\s+", " ", (line or "").lower().strip())
        if norm not in banned:
            return line
    return pools[0]


def pick_photo_refusal_fallback(
    fan_message: str = "",
    *,
    turns: Optional[List[Dict[str, Any]]] = None,
    banned: set[str] | None = None,
) -> str:
    return pick_boundary_fallback(fan_message, turns=turns, banned=banned)


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
