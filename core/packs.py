"""
Situation packs — short MUST/SHOULD/NEVER rules loaded from packs/*.md

Only ONE situational pack enters the live prompt per turn.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

_ROOT = Path(__file__).resolve().parent.parent
_PACKS_DIR = _ROOT / "packs"
_DEFAULT_BUDGET = 900
_DEFAULT_FALLBACK = "phase_spiral"
_DEFAULT_PRIORITY = [
    "delivery_scroll",
    "delivery_missing",
    "ppv_unpaid",
    "react_fan_media",
    "billing_clarify",
    "ask_free_first",
    "escalate_paid",
    "lock_now",
    "tease_heat",
    "rapport",
    "chill",
]


@lru_cache(maxsize=1)
def _load_index() -> dict:
    path = _PACKS_DIR / "_index.json"
    if not path.is_file():
        return {
            "priority": list(_DEFAULT_PRIORITY),
            "fallback": _DEFAULT_FALLBACK,
            "budget_chars": _DEFAULT_BUDGET,
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "priority": list(_DEFAULT_PRIORITY),
            "fallback": _DEFAULT_FALLBACK,
            "budget_chars": _DEFAULT_BUDGET,
        }


def priority_order() -> List[str]:
    idx = _load_index()
    order = idx.get("priority") or list(_DEFAULT_PRIORITY)
    return [str(x) for x in order]


def fallback_pack() -> str:
    return str(_load_index().get("fallback") or _DEFAULT_FALLBACK)


def budget_chars() -> int:
    try:
        return int(_load_index().get("budget_chars") or _DEFAULT_BUDGET)
    except (TypeError, ValueError):
        return _DEFAULT_BUDGET


def list_pack_ids() -> List[str]:
    if not _PACKS_DIR.is_dir():
        return list(_DEFAULT_PRIORITY)
    ids = sorted(
        p.stem
        for p in _PACKS_DIR.glob("*.md")
        if p.is_file() and not p.name.startswith("_")
    )
    return ids or list(_DEFAULT_PRIORITY)


def _clip(text: str, budget: int) -> str:
    t = (text or "").strip()
    if len(t) <= budget:
        return t
    return t[: max(0, budget - 24)].rstrip() + "\n…[pack truncated]"


@lru_cache(maxsize=32)
def _raw_pack(pack_id: str) -> str:
    path = _PACKS_DIR / f"{pack_id}.md"
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def render(pack_id: str, *, facts_line: str = "") -> str:
    """
    Render one pack for the system prompt.
    facts_line: optional one-liner of turn facts (API truth).
    """
    pid = (pack_id or fallback_pack()).strip()
    body = _raw_pack(pid)
    if not body:
        body = _raw_pack(fallback_pack()) or (
            "# rapport\nMUST:\n- Be a person. No PPV pitch this turn."
        )
        pid = fallback_pack() if not _raw_pack(pid) else pid

    # Normalize heading
    body = re.sub(r"^#\s+\S+\s*", f"# {pid}\n", body, count=1)
    parts = [f"SITUATION PACK ({pid}):", body]
    if facts_line and facts_line.strip():
        parts.append(f"TURN FACTS: {facts_line.strip()}")
    return _clip("\n".join(parts), budget_chars())


def pick_by_priority(active: Dict[str, bool]) -> str:
    """First pack in priority order whose flag is True; else fallback."""
    for pid in priority_order():
        if active.get(pid):
            return pid
    return fallback_pack()


def reload() -> None:
    """Clear caches after editing packs on disk."""
    _load_index.cache_clear()
    _raw_pack.cache_clear()
