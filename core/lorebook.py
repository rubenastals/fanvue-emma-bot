"""
Lorebook (SillyTavern "World Info" idea).

Keyword-triggered snippets injected into the prompt ONLY when the recent
conversation mentions a matching key. Keeps the base prompt small while
giving Emma the right ammo exactly when relevant.

Source of truth: core/lorebook.json (hot-reloaded when the file mtime changes).
Edit the JSON for Soft style fixes without needing a full redesign.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

_JSON_PATH = Path(__file__).with_name("lorebook.json")
_LOCK = threading.Lock()
_CACHE: List[Dict] = []
_MTIME: float = -1.0
_LAST_CHECK: float = 0.0
_CHECK_INTERVAL_SEC = 60.0  # cheap mtime poll; full reload only when changed

# Built-in fallback if lorebook.json is missing (deploy safety).
_DEFAULT: List[Dict] = [
    {
        "keys": ["feet", "pies", "foot"],
        "content": "He likes feet. You have a foot/soles set you can tease and lock as PPV.",
    },
    {
        "keys": ["tip", "propina", "gift", "spoil", "regalo"],
        "content": (
            "SPOIL / GIFT topic. Reward Fanvue tips/gifts. For expensive physical gifts: "
            "flirt briefly then redirect to tips/unlocks ON Fanvue — never IRL logistics."
        ),
    },
]


def _parse_entries(raw: object) -> Optional[List[Dict]]:
    if not isinstance(raw, list) or not raw:
        return None
    out: List[Dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        keys = item.get("keys")
        content = (item.get("content") or "").strip()
        if not isinstance(keys, list) or not content:
            continue
        clean_keys = [str(k).strip() for k in keys if str(k).strip()]
        if clean_keys:
            out.append({"keys": clean_keys, "content": content})
    return out or None


def _read_disk() -> List[Dict]:
    try:
        raw = json.loads(_JSON_PATH.read_text(encoding="utf-8"))
        parsed = _parse_entries(raw)
        if parsed:
            return parsed
    except (OSError, json.JSONDecodeError):
        pass
    return list(_DEFAULT)


def ensure_fresh(*, force: bool = False) -> bool:
    """
    Reload lorebook.json if mtime changed.
    Returns True if the in-memory entries were replaced.
    """
    global _CACHE, _MTIME, _LAST_CHECK
    now = time.monotonic()
    with _LOCK:
        if not force and _CACHE and (now - _LAST_CHECK) < _CHECK_INTERVAL_SEC:
            return False
        _LAST_CHECK = now
        try:
            mtime = _JSON_PATH.stat().st_mtime if _JSON_PATH.exists() else 0.0
        except OSError:
            mtime = 0.0
        if not force and _CACHE and mtime == _MTIME:
            return False
        _CACHE = _read_disk()
        _MTIME = mtime
        return True


def get_entries() -> List[Dict]:
    ensure_fresh()
    with _LOCK:
        return list(_CACHE)


# Back-compat for anything that still reads LOREBOOK as a module attr.
def __getattr__(name: str):
    if name == "LOREBOOK":
        return get_entries()
    raise AttributeError(name)


def triggered_entries(recent_text: str, *, max_entries: int = 4) -> List[str]:
    low = (recent_text or "").lower()
    hits: List[str] = []
    for entry in get_entries():
        if any(k in low for k in entry["keys"]):
            hits.append(entry["content"])
        if len(hits) >= max_entries:
            break
    return hits


def render_block(recent_text: str) -> str:
    hits = triggered_entries(recent_text)
    if not hits:
        return ""
    return "RELEVANT CONTEXT RIGHT NOW:\n" + "\n".join(f"- {h}" for h in hits)
