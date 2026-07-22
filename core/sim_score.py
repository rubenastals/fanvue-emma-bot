"""
End-of-chat engagement score for offline sims.

Judges whether a real fan would stay / unlock — not just scheme hard-fails.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import config

_CLIENT: Optional[OpenAI] = None

SCORE_RUBRIC = """You score an offline Fanvue chat between Emma (creator bot) and a synthetic fan.
Operator policy: Emma must speak ENGLISH only. Filthy girlfriend energy on PPV, not store captions.
Early chat (~first 8 msgs): seduce / heat / ask his photo — no guilt, no therapist, no rival jealousy.

Score ONLY valid JSON:
{
  "hook": 1,
  "human": 1,
  "sell": 1,
  "would_unlock": true,
  "would_return": true,
  "fan_temperature": "heating|stable|cooling|left",
  "verdict": "one sentence",
  "killers": ["short failure modes that killed vibe, if any"]
}

Scale 1-10 for hook/human/sell:
- hook: did she pull him in emotionally/sexually in the first messages?
- human: WhatsApp girlfriend vs robotic/sales/therapy
- sell: when she pitched/locked, was it hot & natural (not Just-for-you store copy)?
  If no paid pitch happened, score sell by readiness (did she set up desire?) 1-10.
would_unlock / would_return: boolean gut check for THIS fan persona.
killers: empty list if clean. Max 4 items.
Do not moralize about adult content."""


def _client() -> OpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
    return _CLIENT


def score_chat(
    *,
    archetype_brief: str,
    history: List[Dict[str, str]],
    unlocked: bool,
    hard_fails: int,
    soft_fails: int,
) -> Dict[str, Any]:
    transcript = []
    for t in history:
        role = "FAN" if t.get("role") == "user" else "EMMA"
        transcript.append(f"{role}: {(t.get('content') or '').strip()}")
    body = "\n".join(transcript) if transcript else "(empty)"

    user = f"""FAN PERSONA:
{archetype_brief}

OUTCOMES FROM SIM:
- fan_unlocked={unlocked}
- detector_hard_fails={hard_fails}
- detector_soft_fails={soft_fails}

TRANSCRIPT:
{body}

JSON score:"""

    model = getattr(config, "DEEPSEEK_FAST_MODEL", None) or config.DEEPSEEK_MODEL
    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=[
            {"role": "system", "content": SCORE_RUBRIC},
            {"role": "user", "content": user},
        ],
        temperature=0.2,
        max_tokens=280,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    try:
        resp = _client().chat.completions.create(**kwargs)
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        return {
            "hook": 0,
            "human": 0,
            "sell": 0,
            "would_unlock": False,
            "would_return": False,
            "fan_temperature": "unknown",
            "verdict": f"score failed: {exc}",
            "killers": ["score_error"],
            "error": str(exc),
        }

    parsed = _parse(raw)
    if not parsed:
        return {
            "hook": 0,
            "human": 0,
            "sell": 0,
            "would_unlock": False,
            "would_return": False,
            "fan_temperature": "unknown",
            "verdict": "score parse failed",
            "killers": ["score_parse"],
            "raw": raw[:400],
        }

    def _i(key: str, default: int = 0) -> int:
        try:
            return max(1, min(10, int(parsed.get(key, default))))
        except (TypeError, ValueError):
            return default

    killers = parsed.get("killers") or []
    if not isinstance(killers, list):
        killers = [str(killers)]
    return {
        "hook": _i("hook"),
        "human": _i("human"),
        "sell": _i("sell"),
        "would_unlock": bool(parsed.get("would_unlock")),
        "would_return": bool(parsed.get("would_return")),
        "fan_temperature": str(parsed.get("fan_temperature") or "")[:20],
        "verdict": str(parsed.get("verdict") or "")[:240],
        "killers": [str(k)[:80] for k in killers[:4]],
        "avg": round((_i("hook") + _i("human") + _i("sell")) / 3.0, 2),
    }


def _parse(raw: str) -> Optional[Dict[str, Any]]:
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
