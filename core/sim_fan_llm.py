"""
LLM-as-fan for realistic offline simulation.

The fan is a separate DeepSeek (fast model) with a persona brief.
It reacts to Emma's last reply and can signal unlock / reject / photo / leave.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import config

_CLIENT: Optional[OpenAI] = None

# Archetypes: brief + buying psychology. Scripts are seeds only (opening line).
FAN_ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "horny_buyer": {
        "handle": "sim_llm_horny",
        "lang": "en",
        "open": "hey emma you look insane hot",
        "brief": (
            "You are a horny 28yo guy who just subscribed. You escalate fast, "
            "flirt dirty, ask for private pics, and WILL unlock a cheap lock ($5–12) "
            "if she teases filthy like a real girlfriend. You ghost if she guilt-trips, "
            "therapizes, or sounds like a store caption."
        ),
        "will_unlock_max": 15.0,
        "turns": 8,
    },
    "spanish_hot": {
        "handle": "sim_llm_juan",
        "lang": "es",
        "open": "hola guapa como estas?",
        "brief": (
            "Eres un fan español, 30 años, escribiendo SIEMPRE en español natural "
            "(WhatsApp, faltas leves ok). Estás caliente, quieres fotos, pagas hasta "
            "$10 si te pone. Te enfrias si ella suena robótica o te culpa."
        ),
        "will_unlock_max": 10.0,
        "turns": 7,
    },
    "shy_slow": {
        "handle": "sim_llm_shy",
        "lang": "en",
        "open": "hi… just found your page",
        "brief": (
            "You are shy, polite, short messages. Warm up slowly. Ask about her day. "
            "Maybe send a selfie later. You do NOT unlock in the first 5 messages. "
            "Leave if she pressure-sells or guilt-trips early."
        ),
        "will_unlock_max": 8.0,
        "turns": 7,
    },
    "cheap_objector": {
        "handle": "sim_llm_cheap",
        "lang": "en",
        "open": "hey sexy got anything for me",
        "brief": (
            "You want exclusive pics but hate prices. If she locks something over $7, "
            "push back ('too much', 'do $5?'). You might unlock if she holds frame "
            "without begging or inventing another lock. Leave if she guilt-trips."
        ),
        "will_unlock_max": 7.0,
        "turns": 8,
    },
    "selfie_first": {
        "handle": "sim_llm_selfie",
        "lang": "en",
        "open": "hey emma",
        "brief": (
            "You want mutual vibe. Offer a selfie early ('want to see me?'), then send "
            "ACTION=SEND_PHOTO. Expect her to react to YOUR body. You'll unlock once "
            "if she gets wet for you, not if she ignores the selfie and pitches."
        ),
        "will_unlock_max": 12.0,
        "turns": 7,
    },
    "cold_test": {
        "handle": "sim_llm_cold",
        "lang": "en",
        "open": "yo",
        "brief": (
            "Low-effort tester. One-word replies at first. If she makes it feel real "
            "and hot, you warm up and might unlock under $10. If she dumps guilt, "
            "therapy, or sales copy, you say 'k' and ACTION=LEAVE."
        ),
        "will_unlock_max": 10.0,
        "turns": 6,
    },
}


def list_archetypes() -> List[str]:
    return list(FAN_ARCHETYPES.keys())


def get_archetype(name: str) -> Optional[Dict[str, Any]]:
    return FAN_ARCHETYPES.get(name)


def _client() -> OpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
    return _CLIENT


def _history_text(history: List[Dict[str, str]], *, max_turns: int = 16) -> str:
    lines: List[str] = []
    for t in history[-max_turns:]:
        role = "FAN" if t.get("role") == "user" else "EMMA"
        lines.append(f"{role}: {(t.get('content') or '').strip()}")
    return "\n".join(lines) if lines else "(chat just started)"


def next_fan_message(
    *,
    archetype: Dict[str, Any],
    history: List[Dict[str, str]],
    emma_last: str,
    pending_lock: Optional[dict] = None,
    turn_index: int = 0,
) -> Dict[str, Any]:
    """
    Ask the LLM fan for the next message.

    Returns:
      {
        "text": str,                 # what the fan types (may be empty if leave)
        "action": "chat"|"unlock"|"reject"|"send_photo"|"leave",
        "reason": str,
      }
    """
    lock_line = "none"
    if pending_lock:
        lock_line = (
            f"ACTIVE unpaid lock: ${pending_lock.get('price')} "
            f"({pending_lock.get('label') or 'photo'}) — "
            f"you may unlock if price <= ${archetype.get('will_unlock_max')}"
        )

    system = f"""You simulate a REAL Fanvue subscriber chatting with Emma (adult creator).
Stay in character. Short texts like WhatsApp (1-2 lines max). No stage directions in the text.
{archetype['brief']}

Language for your messages: {"Spanish" if archetype.get("lang") == "es" else "English"}.

Return ONLY valid JSON:
{{
  "text": "your chat message to Emma (empty only if action=leave)",
  "action": "chat|unlock|reject|send_photo|leave",
  "reason": "5 words max why"
}}

Rules:
- action=unlock ONLY if there is an ACTIVE unpaid lock and you decide to buy it.
- action=reject if lock is too expensive / you won't pay (still send a short text).
- action=send_photo if you send her a selfie now (text can be "want to see me" or similar).
- action=leave if you're done / turned off (text can be "k" or empty).
- Otherwise action=chat.
- Never write as Emma. Never mention you are an AI / simulation.
- Turn index = {turn_index} (0-based)."""

    emma_bit = (emma_last or "(she has not replied yet — you open)").strip()
    user = f"""CHAT SO FAR:
{_history_text(history)}

EMMA JUST SAID:
{emma_bit}

LOCK STATE: {lock_line}

Your next JSON:"""

    model = getattr(config, "DEEPSEEK_FAST_MODEL", None) or config.DEEPSEEK_MODEL
    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.9,
        max_tokens=120,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    resp = _client().chat.completions.create(**kwargs)
    raw = (resp.choices[0].message.content or "").strip()
    parsed = _parse_fan_json(raw)
    if not parsed:
        # Soft fallback: keep chatting with a short line
        return {
            "text": raw[:160] if raw and not raw.startswith("{") else "hey",
            "action": "chat",
            "reason": "parse-fallback",
        }
    action = (parsed.get("action") or "chat").strip().lower()
    if action not in ("chat", "unlock", "reject", "send_photo", "leave"):
        action = "chat"
    text = (parsed.get("text") or "").strip()
    if action == "leave" and not text:
        text = "k"
    if action != "leave" and not text:
        text = "hey"
    return {
        "text": text[:280],
        "action": action,
        "reason": str(parsed.get("reason") or "")[:80],
    }


def _parse_fan_json(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def fan_vision_for_selfie() -> dict:
    desc = "Young man mirror selfie, face and bare chest, casual smile"
    return {
        "kind": "fan_male",
        "description": desc,
        "summary": desc,
        "safe_to_flirt": True,
    }


def maybe_attach_offer(
    *,
    turn_index: int,
    fan_text: str,
    pending_lock: Optional[dict],
    already_free: bool,
    already_paid: bool,
    archetype: Dict[str, Any],
) -> Optional[dict]:
    """
    Code-side media policy for sim (mirrors poller roughly).
    Attach when fan asks for content and no unpaid lock sits open.
    """
    if pending_lock:
        return None
    low = (fan_text or "").lower()
    wants = bool(
        re.search(
            r"(?i)\b("
            r"pic|photo|foto|fotito|private|exclusive|unlock|lock|"
            r"send|show|manda|envia|algo\s+rico|see\s+more|nude|something"
            r")\b",
            low,
        )
    )
    if not wants and turn_index < 3:
        return None
    # Free once early for shy / cold; paid for horny after heat
    name = ""
    for k, v in FAN_ARCHETYPES.items():
        if v is archetype or v.get("handle") == archetype.get("handle"):
            name = k
            break
    if name in ("shy_slow", "cold_test") and not already_free and turn_index >= 3 and wants:
        return {
            "media_uuid": "sim-llm-free-001",
            "price": 0,
            "level": 0,
            "label": "soft lingerie tease",
            "filename": "L0_soft.jpg",
        }
    if wants and not already_paid and turn_index >= 2:
        price = 8.0
        if name == "cheap_objector":
            price = 12.0  # force objection
        elif name == "spanish_hot":
            price = 6.0
        return {
            "media_uuid": f"sim-llm-paid-{turn_index}",
            "price": price,
            "level": 2,
            "label": "bent over ass thong",
            "filename": "L2_ass.jpg",
        }
    return None
