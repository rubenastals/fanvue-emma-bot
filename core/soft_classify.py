"""
Optional cheap DeepSeek JSON boolean classifier for ambiguous turns.

Does NOT write Emma's reply. Only returns intent booleans + pack_hint.
Enabled with SOFT_CLASSIFY=1.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from core import packs
from core.turn_facts import TurnFacts

_VALID_BOOLS = (
    "ask_free",
    "missing_delivery",
    "buying",
    "horny",
    "smalltalk",
    "pushback_billing",
    "want_another",
)


def classify(
    fan_message: str,
    *,
    history_snippets: Optional[List[str]] = None,
    facts: Optional[TurnFacts] = None,
) -> Optional[Dict[str, Any]]:
    from config import config
    from openai import OpenAI

    if not getattr(config, "SOFT_CLASSIFY", False):
        return None
    if not config.DEEPSEEK_API_KEY:
        return None

    pack_ids = packs.list_pack_ids()
    hist = "\n".join((history_snippets or [])[-5:])
    sys = (
        "You classify Fanvue DM intents. Reply with ONLY compact JSON. "
        "No prose. Booleans must be true/false. "
        f"pack_hint must be one of: {', '.join(pack_ids)}."
    )
    user = (
        f"Fan message:\n{(fan_message or '')[:500]}\n\n"
        f"Recent lines:\n{hist[:800] or '(none)'}\n\n"
        "Return JSON keys: ask_free, missing_delivery, buying, horny, "
        "smalltalk, pushback_billing, want_another, pack_hint."
    )
    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
    )
    kwargs: Dict[str, Any] = dict(
        model=getattr(config, "SOFT_CLASSIFY_MODEL", None) or config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": user},
        ],
        temperature=0,
        max_tokens=150,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    try:
        resp = client.chat.completions.create(**kwargs)
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"   soft-classify failed: {type(e).__name__}: {e}")
        return None

    return _parse_json(raw, pack_ids)


def _parse_json(raw: str, pack_ids: List[str]) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    text = raw.strip()
    # Strip markdown fences
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    out: Dict[str, Any] = {}
    for k in _VALID_BOOLS:
        if k in data:
            out[k] = bool(data[k])
    hint = str(data.get("pack_hint") or "").strip()
    if hint in pack_ids:
        out["pack_hint"] = hint
    return out or None
