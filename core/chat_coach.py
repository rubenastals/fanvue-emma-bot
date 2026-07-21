"""
Chat Coach — per-fan 24h DeepSeek review of conversation quality.

Every 24h, analyzes the last conversation turns from the perspective of:
- Emotional bonding (parasocial relationship quality)
- Monetization (PPV sales, timing, missed opportunities)
- What Emma is doing wrong specifically with THIS fan

Adds 3-5 actionable bullet points to the CLIENT CARD so DeepSeek reads
them on every subsequent request for that fan.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from config import config

_COACH_INTERVAL_HOURS = 24


def _stale(mem: dict) -> bool:
    raw = mem.get("last_coach_at")
    if not raw:
        return int(mem.get("messages") or 0) >= 10
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - dt >= timedelta(hours=_COACH_INTERVAL_HOURS)
    except (TypeError, ValueError):
        return True


def _format_turns(turns: List[Dict[str, str]], *, max_turns: int = 40) -> str:
    lines = []
    for t in (turns or [])[-max_turns:]:
        role = (t.get("role") or "").lower()
        who = "Emma" if role == "assistant" else "Fan"
        content = (t.get("content") or "").replace("\n", " ")[:200]
        if content:
            lines.append(f"{who}: {content}")
    return "\n".join(lines) or "(no turns)"


def run_coach(
    fan_uuid: str,
    fan_handle: str,
    turns: List[Dict[str, str]],
    mem: dict,
) -> Optional[List[str]]:
    """
    Analyze conversation and return 3-5 coaching bullet points.
    Returns None if not due or API unavailable.
    """
    if not _stale(mem):
        return None

    api_key = (getattr(config, "DEEPSEEK_API_KEY", "") or "").strip()
    if not api_key:
        return None

    from openai import OpenAI
    client = OpenAI(
        api_key=api_key,
        base_url=getattr(config, "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
    )

    spent = float(mem.get("fanvue_spent_usd") or mem.get("total_spent") or 0)
    purchases = int(mem.get("purchases") or 0)
    msgs = int(mem.get("messages") or 0)
    status = mem.get("fanvue_status") or "unknown"

    system = (
        "You are a blunt Fanvue chatter coach reviewing Emma's conversations. "
        "Your goal: Emma must bond emotionally with the fan AND monetize him (PPV unlocks, tips). "
        "Read the conversation and identify what Emma is doing WRONG or missing. "
        "Be specific, critical, and actionable — not generic. "
        "Output a JSON array of 3-5 short bullet strings (max 120 chars each). "
        "Focus on: missed sale moments, emotional bond failures, repetitive patterns, "
        "wrong tone for this specific fan, opportunities she didn't take. "
        'Format: ["point 1", "point 2", ...]'
    )
    user = (
        f"Fan: @{fan_handle} | msgs={msgs} | spent=${spent:.2f} | "
        f"purchases={purchases} | fanvue_status={status}\n\n"
        f"Recent conversation (last 40 turns):\n{_format_turns(turns)}\n\n"
        "What is Emma doing wrong or missing with THIS specific fan?"
    )

    try:
        kwargs: Dict[str, Any] = {
            "model": getattr(config, "DEEPSEEK_FAST_MODEL", None) or config.DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.4,
            "max_tokens": 400,
        }
        if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
            kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

        resp = client.chat.completions.create(**kwargs)
        raw = (resp.choices[0].message.content or "").strip()
        match = __import__("re").search(r"\[[\s\S]*?\]", raw)
        if not match:
            return None
        notes = json.loads(match.group(0))
        if not isinstance(notes, list):
            return None
        return [str(n).strip() for n in notes if str(n).strip()][:5]
    except Exception as e:
        print(f"   ⚠️ chat coach failed: {type(e).__name__}: {e}")
        return None


def run_coach_async(
    fan_uuid: str,
    fan_handle: str,
    turns: List[Dict[str, str]],
    mem: dict,
) -> None:
    """Run coach in background thread — non-blocking."""
    import threading

    def _run():
        notes = run_coach(fan_uuid, fan_handle, turns, mem)
        if notes:
            try:
                from core import fan_memory
                fan_memory.patch_fanvue_platform(
                    fan_uuid,
                    {
                        "coach_notes": notes,
                        "last_coach_at": datetime.now(timezone.utc).isoformat(),
                    },
                    fan_handle=fan_handle,
                )
                print(f"   \U0001f3af coach: {len(notes)} notes saved for @{fan_handle}")
            except Exception as e:
                print(f"   \u26a0\ufe0f coach save failed: {e}")

    threading.Thread(target=_run, daemon=True).start()
