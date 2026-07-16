"""
Per-fan memory (SillyTavern "lorebook per character" idea, no Postgres).

Stores durable facts about each fan in a JSON file so Emma stays coherent
across sessions: name, kinks/likes he mentioned, what he bought, spend,
last price offered, and a short free-form note.

Injected into the prompt as a compact context block.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from db import fan_memory_store

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FILE = os.path.join(_ROOT, ".fan_memory.json")
_LOCK = threading.Lock()

# Cheap kink/interest detection so Emma "remembers" what he's into.
_INTEREST_KEYWORDS = {
    "feet": ("feet", "pies", "foot"),
    "ass": ("ass", "culo", "booty", "fat ass"),
    "pussy": ("pussy", "coño", "cono"),
    "dirty talk": ("dirty", "nasty", "guarra", "talk dirty"),
    "domination": ("dominate", "domina", "boss", "obey", "sumiso", "submissive"),
    "roleplay": ("roleplay", "pretend", "fantasy", "fantasía"),
    "videos": ("video", "vid", "clip"),
    "photos": ("photo", "foto", "pic", "pics", "picture"),
    "custom": ("custom", "personalizado", "just for me", "para mi"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_all() -> Dict[str, dict]:
    """Bulk load (migrate / rare). Prefer get()/set_fan for per-fan updates."""
    return fan_memory_store.load_all()


def _save_all(data: Dict[str, dict]) -> None:
    fan_memory_store.save_all(data)


def _put(fan_uuid: str, mem: dict) -> None:
    fan_memory_store.set_fan(fan_uuid, mem)


def get(fan_uuid: str) -> dict:
    with _LOCK:
        return fan_memory_store.get_fan(fan_uuid)


def _guess_name_from_handle(handle: str) -> str:
    """Best-effort first name from @handle (not perfect, better than nothing)."""
    h = (handle or "").lstrip("@").strip()
    if not h:
        return ""
    # drop common prefixes
    for pref in ("im.", "its.", "the.", "real.", "official."):
        if h.lower().startswith(pref):
            h = h[len(pref) :]
    token = re.split(r"[._\-\d]+", h)[0] if h else ""
    if len(token) < 2 or len(token) > 16:
        return ""
    if not token.isalpha():
        return ""
    return token[:1].upper() + token[1:].lower()


def _blank(fan_handle: str) -> dict:
    return {
        "handle": fan_handle,
        "name": _guess_name_from_handle(fan_handle),
        "first_seen": _now(),
        "messages": 0,
        "interests": [],
        "total_spent": 0.0,
        "purchases": 0,
        "last_offer": None,
        "last_offer_at": None,
        "offers_today": 0,
        "offers_day": None,  # YYYY-MM-DD UTC
        "last_reject_at": None,
        "chill_until": None,
        "last_mode": None,
        "last_offer_level": 0,
        "sent_media_uuids": [],
        "prefer_spanish": False,
        "nudge_sent_episode": False,
        "last_nudge_at": None,
        "last_goodmorning_day": None,  # YYYY-MM-DD local
        "note": "",
        "status": "new",  # new | warm | spender | whale | cold
    }


_NAME_PATTERNS = (
    r"\b(?:my name is|i'?m|i am|me llamo|soy)\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,16})\b",
    r"\bcall me\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,16})\b",
)


def observe_message(fan_uuid: str, fan_handle: str, text: str) -> dict:
    """Update memory from an incoming fan message (cheap heuristics)."""
    low = (text or "").lower()
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        mem["handle"] = fan_handle or mem.get("handle")
        if not mem.get("name"):
            mem["name"] = _guess_name_from_handle(mem.get("handle") or fan_handle)
        mem["messages"] = int(mem.get("messages", 0)) + 1
        mem["last_seen"] = _now()
        # He answered → the silence episode is over, nudges re-armed
        mem["nudge_sent_episode"] = False

        for pat in _NAME_PATTERNS:
            m = re.search(pat, text or "", flags=re.IGNORECASE)
            if m:
                raw = m.group(1).strip()
                if raw.lower() not in {
                    "here", "just", "the", "not", "horny", "hard", "ready", "back",
                    "good", "fine", "okay", "free", "down",
                }:
                    mem["name"] = raw[:1].upper() + raw[1:].lower()
                break

        interests = set(mem.get("interests", []))
        for label, kws in _INTEREST_KEYWORDS.items():
            if any(k in low for k in kws):
                interests.add(label)
        mem["interests"] = sorted(interests)

        if mem.get("status") == "new" and mem["messages"] >= 3:
            mem["status"] = "warm"

        _put(fan_uuid, mem)
        return mem


def record_purchase(fan_uuid: str, amount: float, fan_handle: str = "") -> dict:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        mem["purchases"] = int(mem.get("purchases", 0)) + 1
        mem["total_spent"] = round(float(mem.get("total_spent", 0)) + float(amount), 2)
        mem["last_purchase_at"] = _now()
        # After a buy: reward window — no pitching for a bit
        mem["chill_until"] = (
            datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=45)
        ).isoformat()
        if mem["total_spent"] >= 200:
            mem["status"] = "whale"
        elif mem["total_spent"] > 0:
            mem["status"] = "spender"
        _put(fan_uuid, mem)
        return mem


def set_last_offer(
    fan_uuid: str,
    price: Optional[float] = None,
    fan_handle: str = "",
    *,
    level: Optional[int] = None,
    media_uuid: Optional[str] = None,
    label: Optional[str] = None,
) -> None:
    """Record that Emma pitched (optionally with a price / media)."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if mem.get("offers_day") != today:
            mem["offers_today"] = 0
            mem["offers_day"] = today
        if price is not None:
            mem["last_offer"] = float(price)
        if level is not None:
            mem["last_offer_level"] = int(level)
        if media_uuid:
            sent = list(mem.get("sent_media_uuids") or [])
            if media_uuid not in sent:
                sent.append(media_uuid)
            mem["sent_media_uuids"] = sent[-80:]
            # Track THE most recent locked PPV for truth-checking claims
            mem["last_ppv_media_uuid"] = media_uuid
            mem["last_ppv_at"] = _now()
            mem["last_ppv_price"] = float(price) if price is not None else None
            mem["last_ppv_label"] = label or ""
        mem["last_offer_at"] = _now()
        mem["offers_today"] = int(mem.get("offers_today", 0)) + 1
        _put(fan_uuid, mem)


def record_reject(fan_uuid: str, fan_handle: str = "", minutes: int = 120) -> dict:
    """Fan pushed back on price / said later — open a chill window."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        mem["last_reject_at"] = _now()
        mem["chill_until"] = (
            datetime.now(timezone.utc).replace(microsecond=0)
            + timedelta(minutes=minutes)
        ).isoformat()
        _put(fan_uuid, mem)
        return mem


def set_last_mode(fan_uuid: str, mode: str, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        mem["last_mode"] = mode
        _put(fan_uuid, mem)


def set_prefer_spanish(fan_uuid: str, prefer: bool, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        mem["prefer_spanish"] = bool(prefer)
        _put(fan_uuid, mem)


def mark_nudge(fan_uuid: str, kind: str, fan_handle: str = "") -> None:
    """kind: 'nudge' (5-min rescue) or 'goodmorning' (next-day)."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        if kind == "nudge":
            mem["nudge_sent_episode"] = True
            mem["last_nudge_at"] = _now()
        elif kind == "goodmorning":
            from core import persona_time

            mem["last_goodmorning_day"] = persona_time.la_today()
            mem["nudge_sent_episode"] = True
        _put(fan_uuid, mem)


def set_note(fan_uuid: str, note: str, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        mem["note"] = note
        _put(fan_uuid, mem)


def set_last_fan_image(
    fan_uuid: str,
    description: str,
    *,
    media_uuid: Optional[str] = None,
    fan_handle: str = "",
) -> None:
    """Remember what Grok saw in the fan's last photo (for 'qué es?' follow-ups)."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        mem["last_fan_image_desc"] = (description or "").strip()[:800]
        mem["last_fan_image_at"] = _now()
        if media_uuid:
            mem["last_fan_image_uuid"] = media_uuid
        _put(fan_uuid, mem)


def render_block(fan_uuid: str) -> str:
    """Compact memory block to inject into the prompt (empty if nothing useful)."""
    mem = get(fan_uuid)
    if not mem:
        return ""
    bits: List[str] = []
    if mem.get("handle"):
        bits.append(f"Fan: @{mem['handle']}")
    if mem.get("name"):
        bits.append(
            f"His name: {mem['name']} — use it sometimes for closeness; "
            f"don't spam pet names"
        )
    if mem.get("prefer_spanish"):
        bits.append("Language pref: Spanish (he asked) — full Spanish only, no English mix")
    else:
        bits.append("Language rule: mirror his language — Spanish msg → full Spanish reply; else English; never mix")
    if mem.get("status"):
        bits.append(f"Status: {mem['status']}")
    if mem.get("messages"):
        bits.append(f"Messages exchanged: {mem['messages']}")
    if mem.get("total_spent"):
        bits.append(f"Total spent: ${mem['total_spent']}")
    if mem.get("purchases"):
        bits.append(f"Purchases: {mem['purchases']}")
    if mem.get("interests"):
        bits.append(f"He's into: {', '.join(mem['interests'])}")
    if mem.get("last_offer"):
        bits.append(f"Last price you offered: ${mem['last_offer']}")
    if mem.get("last_mode"):
        bits.append(f"Last turn mode: {mem['last_mode']}")
    if mem.get("chill_until"):
        bits.append(f"Chill until (UTC): {mem['chill_until']}")
    if mem.get("note"):
        bits.append(f"Note: {mem['note']}")
    if mem.get("last_fan_image_desc"):
        bits.append(
            "Last photo HE sent you (vision): "
            f"{mem['last_fan_image_desc'][:280]} — if he asks what you see, use this"
        )
    if not bits:
        return ""
    return "WHAT YOU REMEMBER ABOUT HIM:\n" + "\n".join(f"- {b}" for b in bits)
