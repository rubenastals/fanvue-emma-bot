"""
Async client-card extractor — DeepSeek pulls durable facts the FAN stated.

Runs in a background thread after each turn (never blocks chat).
Only stores facts explicitly said by the fan — never Emma's inventions.
"""
from __future__ import annotations

import json
import re
import threading
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import config
from core import convo_log, fan_memory

_CLIENT: Optional[OpenAI] = None
_client_lock = threading.Lock()
# Per-fan running guard: prevents concurrent extractor threads for the same fan.
_running: dict[str, bool] = {}
_running_lock = threading.Lock()

EXTRACT_PROMPT = """You maintain a CLIENT CARD for a Fanvue fan chatting with Emma.

From the conversation snippet + current card, extract ONLY facts the FAN explicitly stated
or clearly confirmed about himself. Do NOT invent. Do NOT copy Emma's assumptions.

Return ONLY valid JSON:
{
  "profile": {"name": "", "age": "", "city": "", "job": "", "relationship": "", "kids": "", "hobbies": ""},
  "facts": ["short durable fact", "..."],
  "avoid": ["thing Emma must never invent or repeat wrongly"],
  "summary": "2-4 sentences: who he is + relationship + CURRENT open thread (what you two are mid-talking about right now)"
}

Rules:
- Empty string / empty list when unknown.
- profile.name: ONLY from fan saying "me llamo X" / "my name is X" / "call me X".
  NEVER from Emma guessing. If fan says "no soy X" / "me llamaste X", put X in avoid and clear name.
- profile fields: only if fan stated them.
- facts: lasting personal details (divorce, plays football, lives in X, job stress, family issues, health,
  problems he opened up about, stories he shared — anything he'd expect Emma to remember).
  Capture personal problems/stories explicitly: "stressed about job at [company]", "going through divorce",
  "his dog died", "trouble with his boss", etc. These are CRITICAL for Emma's memory.
- avoid: corrections like "his name is not Jamie", "he did not send a car gift".
- summary: grounded in evidence; if little is known, keep it short.
  ALWAYS include the live thread beat when clear (e.g. "grieving his dog and asking for comfort",
  "haggling a $4 lingerie lock", "angry about spam PPVs but still flirting"). This stops Emma restarting.
- Max 6 new facts, max 3 avoid items this turn.
- No moralizing. Adult chat is fine."""


def _client() -> OpenAI:
    global _CLIENT
    with _client_lock:
        if _CLIENT is None:
            _CLIENT = OpenAI(
                api_key=config.DEEPSEEK_API_KEY,
                base_url=config.DEEPSEEK_BASE_URL,
            )
        return _CLIENT


def _snippet(fan_uuid: str) -> str:
    records = convo_log.read_recent(fan_uuid, max_records=48)
    lines: List[str] = []
    for r in records:
        if r.get("type") != "turn":
            continue
        lines.append(f"FAN: {r.get('fan_message', '')}")
        lines.append(f"EMMA: {r.get('reply', '')}")
    return "\n".join(lines[-80:])


def _current_card_text(mem: dict) -> str:
    return json.dumps(
        {
            "name": mem.get("name"),
            "name_confirmed": mem.get("name_confirmed"),
            "profile": mem.get("profile") or {},
            "facts": mem.get("facts") or [],
            "avoid": mem.get("avoid") or [],
            "summary": mem.get("summary") or "",
            "interests": mem.get("interests") or [],
        },
        ensure_ascii=False,
    )


def _parse_json(raw: str) -> Optional[dict]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None


def update_fan_card(fan_uuid: str, fan_handle: str = "") -> Optional[Dict[str, Any]]:
    """Synchronous extract + merge. Returns merge payload or None."""
    mem = fan_memory.get(fan_uuid) or {}
    convo = _snippet(fan_uuid)
    if not convo.strip():
        return None

    kwargs = dict(
        model=getattr(config, "DEEPSEEK_FAST_MODEL", None) or config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": EXTRACT_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Fan @{fan_handle or mem.get('handle') or fan_uuid[:8]}\n"
                    f"CURRENT CARD:\n{_current_card_text(mem)}\n\n"
                    f"RECENT CONVERSATION:\n{convo}"
                ),
            },
        ],
        temperature=0.2,
        max_tokens=400,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    try:
        resp = _client().chat.completions.create(**kwargs)
        raw = (resp.choices[0].message.content or "").strip()
    except Exception:
        return None

    data = _parse_json(raw)
    if not isinstance(data, dict):
        return None

    # Drop empty profile keys
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    profile = {
        k: str(v).strip()
        for k, v in profile.items()
        if v is not None and str(v).strip() and str(v).strip().lower() not in
        ("null", "none", "unknown", "n/a", "")
    }
    facts = [str(x).strip() for x in (data.get("facts") or []) if str(x).strip()][:5]
    avoid = [str(x).strip() for x in (data.get("avoid") or []) if str(x).strip()][:3]
    summary = str(data.get("summary") or "").strip()

    if not profile and not facts and not avoid and not summary:
        return None

    payload = {
        "profile": profile,
        "facts": facts,
        "avoid": avoid,
        "summary": summary,
    }
    fan_memory.apply_card_update(fan_uuid, payload, fan_handle=fan_handle)
    return payload


def update_fan_card_async(fan_uuid: str, fan_handle: str = "") -> None:
    with _running_lock:
        if _running.get(fan_uuid):
            return  # already running for this fan — skip duplicate
        _running[fan_uuid] = True

    def _run():
        try:
            update_fan_card(fan_uuid, fan_handle)
        finally:
            with _running_lock:
                _running.pop(fan_uuid, None)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
