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

EXTRACT_PROMPT = """You maintain a CLIENT CARD for a Fanvue fan chatting with Emma.

From the conversation snippet + current card, extract ONLY facts the FAN explicitly stated
or clearly confirmed about himself. Do NOT invent. Do NOT copy Emma's assumptions.

Return ONLY valid JSON:
{
  "profile": {"name": "", "age": "", "city": "", "job": "", "relationship": "", "kids": "", "hobbies": ""},
  "facts": ["short durable fact", "..."],
  "avoid": ["thing Emma must never invent or repeat wrongly"],
  "summary": "2-4 sentences about who he is and the relationship so far"
}

Rules:
- Empty string / empty list when unknown.
- profile fields: only if fan stated them.
- facts: lasting personal details (divorce, plays football, lives in X, bought Y for her, etc.).
- avoid: corrections like "his name is not Jamie", "he did not send a car gift".
- summary: grounded in evidence; if little is known, keep it short.
- Max 5 new facts, max 3 avoid items this turn.
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
    records = convo_log.read_recent(fan_uuid, max_records=24)
    lines: List[str] = []
    for r in records:
        if r.get("type") != "turn":
            continue
        lines.append(f"FAN: {r.get('fan_message', '')}")
        lines.append(f"EMMA: {r.get('reply', '')}")
    return "\n".join(lines[-40:])


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
        model=config.DEEPSEEK_MODEL,
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
    t = threading.Thread(
        target=update_fan_card,
        args=(fan_uuid, fan_handle),
        daemon=True,
    )
    t.start()
