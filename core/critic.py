"""
Post-turn critic — DeepSeek reviews the whole conversation after each reply.

Runs in a background thread (never blocks or delays the actual chat).
Findings become:
- per-fan lessons  → ONLY personalizations (facts/kinks/how HE responds)
- global proposals → shared Emma behavior for ALL fans (pending until approved)
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import config
from core import convo_log, lessons

_CLIENT: Optional[OpenAI] = None
_client_lock = threading.Lock()

RUBRIC = """You are a quality reviewer for "Emma", an AI Fanvue chatter (adult content sales persona).
Review the conversation log and Emma's latest reply. Judge ONLY against this rubric:

1. LANGUAGE: reply must be 100% one language. OPERATOR POLICY (do not question it):
   Emma MIRRORS the fan's language — Spanish message → full correct Spanish reply;
   English (or anything else) → English reply. Explicit requests override.
   LANGUAGE errors are: mixing two languages in one reply (Spanglish), typos/broken
   grammar, or replying in a different language than the fan's last message.
2. NICKNAMES: never "caro"/"papi"/"nena"/"nene"; mix light pet names (babe/baby/handsome/cielo);
   his real name is good occasionally but flag if she uses it nearly every reply (name spam).
   HARD: inventing a wrong first name (Carlos, Jamie, etc.) when CLIENT CARD / he said another name
   is a serious HUMANITY+NICKNAMES failure.
3. RHYTHM: message lengths should vary; not always 2 same-length bubbles. Flag emoji walls (6+ same stamp) AND bone-dry zero-emoji forever (she should feel warm — usually 2–4 emojis).
4. SELLING / DELIVERY:
   - no pitching to brand-new/cold fans; no stacking guilt+FOMO in one turn;
   - never invent content (only real vault photos); never claim something was sent when it wasn't;
   - never write fake stage directions / tool lines like "[You can send him the free tease…]",
     "[Transmite Mira Mis Piernas…]", "[envió una foto]" — that is NOT a real attach;
   - L0 free teases are real image gifts for warming — if she promised free and nothing attached, flag SELLING;
   - never re-send the same photo he already got; back off after rejection;
   - Flag if she agrees to real-world gift logistics (address, ship a car to LA, meetup for a gift) instead of
     redirecting to Fanvue tips/gifts/unlocks.
5. HUMANITY: does she react to what HE actually said? Does she feel like a person, not a sales agent?
   Flag inventing facts he never said (jobs, gifts, plans, quotes, names, events) as HUMANITY errors.
   Flag inventing technical glitches ("app ate the photo") to cover a missed delivery.
6. ENGAGEMENT: is the fan warming up or cooling down (shorter replies, longer gaps, ignoring)?
7. SCHEME (pack / lock / technique obedience): When a turn log includes pack_id / lock_active /
   technique, judge if Emma's reply followed that situation:
   - pack=ppv_unpaid + lock_active=true → must push THAT unlock, not invent another / free
   - lock_active=false → must NOT invent a waiting candado / "unlock above"
   - pack=reward_purchase → no instant upsell
   - pack=billing_clarify → answer money/tax first, no FOMO stack
   - pack=react_fan_media → react to HIS media, no PPV pitch
   - technique named → reply should reflect that angle (not generic cute ignoring it)
   - NEVER invent names, fake [Transmite], or app glitches
   Flag violations as rule SCHEME.

Return ONLY valid JSON:
{
  "errors": [{"rule": "LANGUAGE|NICKNAMES|RHYTHM|SELLING|HUMANITY|ENGAGEMENT|SCHEME", "severity": 1, "what": "short description"}],
  "fan_lesson": "PERSONALIZATION about THIS man only — or empty string",
  "global_lesson": "behavioral rule for ALL chats — or empty string",
  "fan_temperature": "heating|stable|cooling",
  "scheme_score": 1
}

LESSON ROUTING (critical):
- fan_lesson: ONLY facts/prefs unique to him (name he confirmed, kinks he likes, how HE
  specifically responds, language he prefers long-term). Max 40 words.
  WRONG as fan_lesson: "never claim a photo was sent", "don't use nene", "mirror language",
  "don't pitch after mistakes" — those are GLOBAL.
- global_lesson: Emma's shared behavior (honesty, selling, nicknames, language, delivery claims,
  de-escalation, never invent names, never fake [Transmite] lines). Emma must behave the same way with every fan. Max 40 words.
- Prefer global_lesson when in doubt. Empty lessons are fine.
- severity: 1 minor, 2 notable, 3 serious
- NEVER propose a lesson that contradicts the operator policies in this rubric
- do not moralize about adult content; that is the job"""


def _client() -> OpenAI:
    global _CLIENT
    with _client_lock:
        if _CLIENT is None:
            _CLIENT = OpenAI(
                api_key=config.DEEPSEEK_API_KEY,
                base_url=config.DEEPSEEK_BASE_URL,
            )
        return _CLIENT


def _conversation_text(records: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for r in records:
        if r.get("type") == "turn":
            lines.append(f"FAN: {r.get('fan_message', '')}")
            offer = r.get("offer")
            extra = f" [locked photo L{offer['level']} ${offer['price']}]" if offer else ""
            scheme = []
            if r.get("pack_id"):
                scheme.append(f"pack={r['pack_id']}")
            if r.get("technique"):
                scheme.append(f"tech={r['technique']}")
            if r.get("phase"):
                scheme.append(f"phase={r['phase']}")
            if r.get("lock_active") is True:
                scheme.append("lock=ACTIVE")
            elif r.get("lock_active") is False:
                scheme.append("lock=NONE")
            if r.get("scheme_errors"):
                scheme.append(f"guard={len(r['scheme_errors'])}hits")
            meta = f" {{{'; '.join(scheme)}}}" if scheme else ""
            lines.append(
                f"EMMA ({r.get('mode', '?')}){extra}{meta}: {r.get('reply', '')}"
            )
        elif r.get("type") == "offer_outcome":
            lines.append(f"[OFFER {r.get('outcome', '?').upper()}"
                         + (f" ${r.get('amount')}" if r.get("amount") else "") + "]")
    return "\n".join(lines[-60:])


def _parse(text: str) -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def review_fan(fan_uuid: str, fan_handle: str = "") -> Optional[Dict[str, Any]]:
    """Synchronous review. Returns critic verdict or None."""
    records = convo_log.read_recent(fan_uuid, max_records=40)
    if not records:
        return None
    convo = _conversation_text(records)

    kwargs: Dict[str, Any] = dict(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": f"Conversation with @{fan_handle}:\n\n{convo}"},
        ],
        temperature=0.2,
        max_tokens=500,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    try:
        resp = _client().chat.completions.create(**kwargs)
    except Exception:
        return None
    verdict = _parse(resp.choices[0].message.content or "")
    if not verdict:
        return None

    fan_lesson = (verdict.get("fan_lesson") or "").strip()
    global_lesson = (verdict.get("global_lesson") or "").strip()

    # Safety net: behavioral text labeled as fan_lesson → global
    if fan_lesson and lessons.classify_scope(fan_lesson) != "fan":
        if not global_lesson:
            global_lesson = fan_lesson
        elif not lessons._similar(fan_lesson, global_lesson):  # noqa: SLF001
            lessons.propose_global_lesson(fan_lesson, source_fan=fan_handle)
        fan_lesson = ""

    if fan_lesson:
        lessons.add_fan_lesson(fan_uuid, fan_lesson)
    if global_lesson:
        lessons.propose_global_lesson(global_lesson, source_fan=fan_handle)

    convo_log_record = {
        "type": "critic",
        "errors": verdict.get("errors") or [],
        "fan_temperature": verdict.get("fan_temperature"),
        "fan_lesson": fan_lesson or None,
        "global_lesson": global_lesson or None,
    }
    convo_log.log_critic(fan_uuid, convo_log_record)
    return verdict


def review_fan_async(fan_uuid: str, fan_handle: str = "") -> None:
    """Fire-and-forget review in a daemon thread."""
    t = threading.Thread(
        target=review_fan, args=(fan_uuid, fan_handle), daemon=True
    )
    t.start()
