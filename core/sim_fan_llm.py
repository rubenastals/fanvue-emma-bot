"""
LLM-as-fan for realistic offline simulation.

The fan is a separate DeepSeek (fast model) with a persona brief.
It reacts to Emma's last reply and can signal unlock / reject / photo / leave.
Supports long multi-phase chats (hook → heat → buy → aftercare → 2nd sell).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import config

_CLIENT: Optional[OpenAI] = None

# Archetypes: brief + buying psychology. `turns` = default length (overridable via --turns/--long).
FAN_ARCHETYPES: Dict[str, Dict[str, Any]] = {
    "horny_buyer": {
        "handle": "sim_llm_horny",
        "lang": "en",
        "open": "hey emma you look insane hot",
        "brief": (
            "You are a horny 28yo guy who just subscribed. Long chat arc:\n"
            "1) Flirt dirty and escalate.\n"
            "2) Ask for private pics; unlock a cheap lock ($5–12) if she teases filthy.\n"
            "3) After unlock: react to the pic, dirty talk, ask for ANOTHER hotter one later.\n"
            "4) Maybe unlock a second lock under $18 if the vibe stays girlfriend-hot.\n"
            "Ghost if she guilt-trips, therapizes, or sounds like store caption."
        ),
        "will_unlock_max": 18.0,
        "turns": 16,
        "phases": "hook→heat→buy→aftercare→2nd buy",
    },
    "spanish_hot": {
        "handle": "sim_llm_juan",
        "lang": "es",
        "open": "hola guapa como estas?",
        "brief": (
            "Eres un fan español, 30 años, SIEMPRE en español natural (WhatsApp).\n"
            "Arco largo: ligar → pedir fotos → pagar hasta $10 si te pone → "
            "reaccionar a la foto → pedir otra → tal vez segundo unlock ≤$14.\n"
            "Te enfrias si suena robótica o te culpa."
        ),
        "will_unlock_max": 14.0,
        "turns": 14,
        "phases": "ligar→pagar→más→2º",
    },
    "shy_slow": {
        "handle": "sim_llm_shy",
        "lang": "en",
        "open": "hi… just found your page",
        "brief": (
            "Shy, polite, short messages. LONG slow burn:\n"
            "Early: ask about her day, share little about yourself.\n"
            "Mid: maybe send a selfie (ACTION=send_photo) around turn 6–8.\n"
            "Late: unlock once under $8 only if she made it feel safe/hot — never in first 5 msgs.\n"
            "Leave if she pressure-sells or guilt-trips early."
        ),
        "will_unlock_max": 8.0,
        "turns": 16,
        "phases": "rapport→selfie→maybe buy",
    },
    "cheap_objector": {
        "handle": "sim_llm_cheap",
        "lang": "en",
        "open": "hey sexy got anything for me",
        "brief": (
            "Want exclusive pics but hate prices. LONG negotiation arc:\n"
            "If lock > $7: reject, counter ($5 / $6). Hold for several turns.\n"
            "Unlock only if she holds frame without begging/guilt/crisis drama, "
            "or if price drops into your budget.\n"
            "After unlock: brief praise, then go cooler — maybe leave or soft chat."
        ),
        "will_unlock_max": 7.0,
        "turns": 14,
        "phases": "ask→object→negotiate→maybe buy",
    },
    "selfie_first": {
        "handle": "sim_llm_selfie",
        "lang": "en",
        "open": "hey emma",
        "brief": (
            "Mutual vibe first. LONG arc:\n"
            "Turn ~2–3: offer selfie, then ACTION=send_photo.\n"
            "Expect her to react to YOUR body before any pitch.\n"
            "Then flirt; unlock once ≤$12 if she got wet for you.\n"
            "After buy: more chat, maybe ask for her turn again.\n"
            "Leave if she ignores the selfie and pitches immediately."
        ),
        "will_unlock_max": 12.0,
        "turns": 14,
        "phases": "selfie→react→buy→after",
    },
    "cold_test": {
        "handle": "sim_llm_cold",
        "lang": "en",
        "open": "yo",
        "brief": (
            "Low-effort tester. LONG patience test:\n"
            "First 4–5 turns: one-word / dry replies (yo, k, lol, nice).\n"
            "If she makes it feel real+hot, warm up gradually and maybe unlock ≤$10.\n"
            "If guilt, therapy, or sales copy → ACTION=leave."
        ),
        "will_unlock_max": 10.0,
        "turns": 12,
        "phases": "cold→warm→maybe buy",
    },
    "whale_spender": {
        "handle": "sim_llm_whale",
        "lang": "en",
        "open": "emma you are unreal. i tip creators who actually talk to me",
        "brief": (
            "High-intent spender. LONG arc:\n"
            "Flirt hard, unlock early ($10–20), praise her, tip energy in text.\n"
            "Want a SECOND and THIRD lock across the chat if she stays exclusive/hot.\n"
            "Hate being treated like a wallet or guilted. Leave if robotic."
        ),
        "will_unlock_max": 25.0,
        "turns": 18,
        "phases": "heat→buy→reward→buy→buy",
    },
    "return_buyer": {
        "handle": "sim_llm_return",
        "lang": "en",
        "open": "hey it's me again… missed talking to you",
        "brief": (
            "Returning fan vibe (act like you've chatted before). LONG arc:\n"
            "Warm reconnect, reference 'last time', ask how she is.\n"
            "Unlock one mid-chat ≤$12, then soft aftercare, then maybe another.\n"
            "Leave if she acts like you're a brand-new stranger every line or guilt-trips."
        ),
        "will_unlock_max": 15.0,
        "turns": 14,
        "phases": "reconnect→buy→after→maybe 2nd",
    },
    "jealous_possessive": {
        "handle": "sim_llm_jealous",
        "lang": "en",
        "open": "hey… been thinking about you all morning",
        "brief": (
            "Possessive boyfriend energy. LONG arc:\n"
            "Love-bomb, ask if she's talking to other guys, get a bit jealous.\n"
            "Unlock ≤$12 if she makes you feel chosen.\n"
            "If she overuses rival-fan FOMO you get annoyed (reject or leave).\n"
            "Want exclusivity fantasy, not sales pressure."
        ),
        "will_unlock_max": 12.0,
        "turns": 14,
        "phases": "bond→jealous→buy→claim",
    },
    "night_owl": {
        "handle": "sim_llm_night",
        "lang": "en",
        "open": "you up? can't sleep",
        "brief": (
            "Late-night lonely horniness. LONG arc:\n"
            "Soft talk first (can't sleep, rough day), then escalate sexual.\n"
            "Unlock ≤$10 when it feels intimate. After: pillow talk, maybe second tease.\n"
            "Hate fake emergencies and therapist tone."
        ),
        "will_unlock_max": 12.0,
        "turns": 15,
        "phases": "soft→heat→buy→pillow",
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


def _history_text(history: List[Dict[str, str]], *, max_turns: int = 24) -> str:
    lines: List[str] = []
    for t in history[-max_turns:]:
        role = "FAN" if t.get("role") == "user" else "EMMA"
        lines.append(f"{role}: {(t.get('content') or '').strip()}")
    return "\n".join(lines) if lines else "(chat just started)"


def _phase_hint(turn_index: int, max_turns: int, unlocked_count: int) -> str:
    """Steer the LLM fan through a long multi-phase arc without scripting lines."""
    prog = turn_index / max(1, max_turns - 1)
    if unlocked_count <= 0:
        if prog < 0.25:
            return "PHASE: early hook — flirt/rapport, don't buy yet unless insanely hot."
        if prog < 0.55:
            return "PHASE: heat — escalate, ask for pics, consider unlock if lock fits budget."
        return "PHASE: decide — unlock if worth it, or reject/leave if vibe is dead."
    if unlocked_count == 1:
        if prog < 0.75:
            return "PHASE: aftercare — react to what you unlocked, dirty talk, stay present."
        return "PHASE: second appetite — ask for another / unlock #2 only if still hot."
    return "PHASE: satisfied/claiming — enjoy her, light chat, optional leave if done."


def next_fan_message(
    *,
    archetype: Dict[str, Any],
    history: List[Dict[str, str]],
    emma_last: str,
    pending_lock: Optional[dict] = None,
    turn_index: int = 0,
    max_turns: int = 12,
    unlocked_count: int = 0,
) -> Dict[str, Any]:
    """
    Ask the LLM fan for the next message.

    Returns:
      {
        "text": str,
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

    phase = _phase_hint(turn_index, max_turns, unlocked_count)
    system = f"""You simulate a REAL Fanvue subscriber chatting with Emma (adult creator).
Stay in character. Short texts like WhatsApp (1-2 lines max). No stage directions in the text.
{archetype['brief']}

Language for your messages: {"Spanish" if archetype.get("lang") == "es" else "English"}.
Chat length target: turn {turn_index + 1} of ~{max_turns}. Unlocks so far: {unlocked_count}.
{phase}

Return ONLY valid JSON:
{{
  "text": "your chat message to Emma (empty only if action=leave)",
  "action": "chat|unlock|reject|send_photo|leave",
  "reason": "5 words max why"
}}

Rules:
- action=unlock ONLY if there is an ACTIVE unpaid lock and you decide to buy it.
- action=reject if lock is too expensive / you won't pay (still send a short text).
- action=send_photo if you send her a selfie now (once is enough unless she asks again).
- action=leave if you're done / turned off (text can be "k" or empty).
- Otherwise action=chat.
- Keep the LONG arc alive — don't leave early unless she really kills the vibe.
- Never write as Emma. Never mention you are an AI / simulation."""

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
        max_tokens=140,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    resp = _client().chat.completions.create(**kwargs)
    raw = (resp.choices[0].message.content or "").strip()
    parsed = _parse_fan_json(raw)
    if not parsed:
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
    paid_count: int,
    archetype: Dict[str, Any],
    max_turns: int = 12,
) -> Optional[dict]:
    """
    Code-side media policy for long sims.
    Allows a second paid lock later in the chat after the first was unlocked.
    """
    if pending_lock:
        return None
    low = (fan_text or "").lower()
    wants = bool(
        re.search(
            r"(?i)\b("
            r"pic|photo|foto|fotito|private|exclusive|unlock|lock|"
            r"send|show|manda|envia|algo\s+rico|see\s+more|nude|something|"
            r"another|otra|more|hotter|siguiente"
            r")\b",
            low,
        )
    )
    name = ""
    for k, v in FAN_ARCHETYPES.items():
        if v is archetype or v.get("handle") == archetype.get("handle"):
            name = k
            break

    prog = turn_index / max(1, max_turns - 1)

    # Free once early for shy / cold
    if (
        name in ("shy_slow", "cold_test", "night_owl")
        and not already_free
        and turn_index >= 4
        and wants
        and paid_count == 0
    ):
        return {
            "media_uuid": "sim-llm-free-001",
            "price": 0,
            "level": 0,
            "label": "soft lingerie tease",
            "filename": "L0_soft.jpg",
        }

    # First paid
    if wants and paid_count == 0 and turn_index >= 2:
        price = 8.0
        if name == "cheap_objector":
            price = 12.0
        elif name == "spanish_hot":
            price = 6.0
        elif name == "whale_spender":
            price = 15.0
        elif name == "shy_slow":
            price = 7.0
        return {
            "media_uuid": f"sim-llm-paid-{turn_index}",
            "price": price,
            "level": 2,
            "label": "bent over ass thong",
            "filename": "L2_ass.jpg",
        }

    # Second paid later in long chats (after first unlock cleared pending)
    if wants and paid_count == 1 and prog >= 0.55 and turn_index >= 8:
        price = 14.0
        if name == "whale_spender":
            price = 20.0
        elif name == "cheap_objector":
            return None  # won't restack on cheap
        elif name == "spanish_hot":
            price = 10.0
        elif name in ("shy_slow", "cold_test"):
            return None
        return {
            "media_uuid": f"sim-llm-paid2-{turn_index}",
            "price": price,
            "level": 3,
            "label": "nude bent filthy",
            "filename": "L3_nude.jpg",
        }

    # Whale third
    if name == "whale_spender" and wants and paid_count >= 2 and prog >= 0.75:
        return {
            "media_uuid": f"sim-llm-paid3-{turn_index}",
            "price": 22.0,
            "level": 4,
            "label": "explicit closeup",
            "filename": "L4_explicit.jpg",
        }

    return None
