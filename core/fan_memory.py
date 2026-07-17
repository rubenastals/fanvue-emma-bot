"""
Per-fan memory — durable client card + sales state.

Stored in Postgres JSONB (or .fan_memory.json fallback). Injected into the
reply prompt as a CLIENT CARD so Emma stays coherent without dumping the
entire chat history every turn.
"""
from __future__ import annotations

import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from db import fan_memory_store

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FILE = os.path.join(_ROOT, ".fan_memory.json")
_LOCK = threading.Lock()

_MAX_FACTS = 20
_MAX_AVOID = 12

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
        "name_confirmed": False,
        "first_seen": _now(),
        "messages": 0,
        "interests": [],
        "total_spent": 0.0,
        "purchases": 0,
        "last_offer": None,
        "last_offer_at": None,
        "offers_today": 0,
        "offers_day": None,
        "last_reject_at": None,
        "chill_until": None,
        "last_mode": None,
        "last_offer_level": 0,
        "sent_media_uuids": [],
        "free_teases_sent": 0,
        "last_free_at": None,
        "prefer_spanish": False,
        "nudge_sent_episode": False,
        "last_nudge_at": None,
        "last_goodmorning_day": None,
        "note": "",
        "status": "new",
        # Permanent client card (hybrid memory)
        "profile": {},
        "facts": [],
        "avoid": [],
        "summary": "",
    }


def _ensure_card_fields(mem: dict) -> None:
    if not isinstance(mem.get("profile"), dict):
        mem["profile"] = {}
    if not isinstance(mem.get("facts"), list):
        mem["facts"] = []
    if not isinstance(mem.get("avoid"), list):
        mem["avoid"] = []
    if "summary" not in mem or mem.get("summary") is None:
        mem["summary"] = ""
    if "name_confirmed" not in mem:
        mem["name_confirmed"] = False


def _dedupe_keep_order(items: List[str], *, limit: int) -> List[str]:
    seen = set()
    out: List[str] = []
    for raw in items:
        s = re.sub(r"\s+", " ", (raw or "").strip())
        if len(s) < 3:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s[:180])
        if len(out) >= limit:
            break
    return out


def apply_card_update(
    fan_uuid: str,
    update: Dict[str, Any],
    *,
    fan_handle: str = "",
) -> dict:
    """
    Merge extractor output into the permanent client card.
    Only confirmed fan-stated facts should be passed here.
    """
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        if fan_handle:
            mem["handle"] = fan_handle

        profile = update.get("profile") if isinstance(update.get("profile"), dict) else {}
        for k, v in profile.items():
            if v is None:
                continue
            s = str(v).strip()
            if not s or s.lower() in ("null", "none", "unknown", "n/a"):
                continue
            key = re.sub(r"[^a-z0-9_]", "", str(k).lower())[:32]
            if not key:
                continue
            mem["profile"][key] = s[:80]
            if key == "name" and len(s) >= 2:
                mem["name"] = s.strip()[:16]
                if mem["name"]:
                    mem["name"] = mem["name"][:1].upper() + mem["name"][1:]
                mem["name_confirmed"] = True

        facts = list(mem.get("facts") or [])
        for f in update.get("facts") or []:
            if isinstance(f, str):
                facts.append(f)
        mem["facts"] = _dedupe_keep_order(facts, limit=_MAX_FACTS)

        avoid = list(mem.get("avoid") or [])
        for a in update.get("avoid") or []:
            if isinstance(a, str):
                avoid.append(a)
        mem["avoid"] = _dedupe_keep_order(avoid, limit=_MAX_AVOID)

        summary = (update.get("summary") or "").strip()
        if summary:
            mem["summary"] = summary[:500]

        _put(fan_uuid, mem)
        return mem


_NAME_PATTERNS = (
    r"\b(?:my name is|i'?m|i am|me llamo|soy)\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,16})\b",
    r"\bcall me\s+([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{2,16})\b",
)


def observe_message(fan_uuid: str, fan_handle: str, text: str) -> dict:
    """Update memory from an incoming fan message (cheap heuristics)."""
    low = (text or "").lower()
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["handle"] = fan_handle or mem.get("handle")
        if not mem.get("name"):
            mem["name"] = _guess_name_from_handle(mem.get("handle") or fan_handle)
            mem["name_confirmed"] = False
        mem["messages"] = int(mem.get("messages", 0)) + 1
        mem["last_seen"] = _now()
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
                    mem["name_confirmed"] = True
                    mem["profile"]["name"] = mem["name"]
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
        _ensure_card_fields(mem)
        mem["purchases"] = int(mem.get("purchases", 0)) + 1
        mem["total_spent"] = round(float(mem.get("total_spent", 0)) + float(amount), 2)
        mem["last_purchase_at"] = _now()
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
        _ensure_card_fields(mem)
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
            mem["last_ppv_media_uuid"] = media_uuid
            mem["last_ppv_at"] = _now()
            mem["last_ppv_price"] = float(price) if price is not None else None
            mem["last_ppv_label"] = label or ""
        mem["last_offer_at"] = _now()
        mem["offers_today"] = int(mem.get("offers_today", 0)) + 1
        _put(fan_uuid, mem)


def record_free_tease(
    fan_uuid: str,
    media_uuid: str,
    *,
    fan_handle: str = "",
    label: str = "",
    level: int = 0,
) -> None:
    """Record an unlocked L0 tease — tracks UUID so it never repeats in this chat."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        sent = list(mem.get("sent_media_uuids") or [])
        if media_uuid not in sent:
            sent.append(media_uuid)
        mem["sent_media_uuids"] = sent[-80:]
        mem["last_free_at"] = _now()
        mem["last_free_media_uuid"] = media_uuid
        mem["last_free_label"] = label or ""
        mem["free_teases_sent"] = int(mem.get("free_teases_sent") or 0) + 1
        if level is not None:
            # Don't overwrite a higher paid last_offer_level with 0
            if int(mem.get("last_offer_level") or 0) <= 0:
                mem["last_offer_level"] = int(level)
        _put(fan_uuid, mem)


def record_reject(fan_uuid: str, fan_handle: str = "", minutes: int = 120) -> dict:
    """Fan pushed back on price / said later — open a chill window."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
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
        _ensure_card_fields(mem)
        mem["last_mode"] = mode
        _put(fan_uuid, mem)


def set_prefer_spanish(fan_uuid: str, prefer: bool, fan_handle: str = "") -> None:
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
        mem["prefer_spanish"] = bool(prefer)
        _put(fan_uuid, mem)


def mark_nudge(fan_uuid: str, kind: str, fan_handle: str = "") -> None:
    """kind: 'nudge' (5-min rescue) or 'goodmorning' (next-day)."""
    with _LOCK:
        mem = fan_memory_store.get_fan(fan_uuid) or _blank(fan_handle)
        _ensure_card_fields(mem)
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
        _ensure_card_fields(mem)
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
        _ensure_card_fields(mem)
        mem["last_fan_image_desc"] = (description or "").strip()[:800]
        mem["last_fan_image_at"] = _now()
        if media_uuid:
            mem["last_fan_image_uuid"] = media_uuid
        _put(fan_uuid, mem)


def render_block(fan_uuid: str) -> str:
    """CLIENT CARD + sales state for the reply prompt."""
    mem = get(fan_uuid)
    if not mem:
        return ""
    _ensure_card_fields(mem)

    lines: List[str] = [
        "CLIENT CARD (confirmed facts only — do NOT invent beyond this + recent chat):",
    ]
    if mem.get("handle"):
        lines.append(f"- Handle: @{mem['handle']}")
    name = (mem.get("name") or "").strip()
    if name:
        conf = (
            "confirmed"
            if mem.get("name_confirmed")
            else "guessed from handle — verify before relying"
        )
        lines.append(
            f"- Name: {name} ({conf}). Use sparingly, not every message; "
            f"prefer pet names (babe/baby/handsome) or none."
        )

    profile = mem.get("profile") or {}
    for key in ("age", "city", "job", "relationship", "kids", "hobbies"):
        if profile.get(key):
            lines.append(f"- {key.capitalize()}: {profile[key]}")
    for key, val in profile.items():
        if key in ("name", "age", "city", "job", "relationship", "kids", "hobbies"):
            continue
        if val:
            lines.append(f"- {key}: {val}")

    facts = mem.get("facts") or []
    if facts:
        lines.append("- Durable facts:")
        for f in facts[-12:]:
            lines.append(f"  • {f}")

    avoid = mem.get("avoid") or []
    if avoid:
        lines.append("- Avoid / never invent:")
        for a in avoid[-8:]:
            lines.append(f"  • {a}")

    if mem.get("summary"):
        lines.append(f"- Rolling summary: {mem['summary']}")

    if mem.get("prefer_spanish"):
        lines.append("- Language: Spanish preferred (full Spanish only)")
    else:
        lines.append("- Language: mirror him (ES→ES, else EN); never mix")

    lines.append(
        f"- Status: {mem.get('status') or 'new'} | msgs: {mem.get('messages') or 0} | "
        f"spent: ${mem.get('total_spent') or 0} | purchases: {mem.get('purchases') or 0}"
    )
    if mem.get("interests"):
        lines.append(f"- Into: {', '.join(mem['interests'])}")
    if mem.get("last_offer"):
        lines.append(f"- Last offer: ${mem['last_offer']}")
    if mem.get("note"):
        lines.append(f"- Operator note: {mem['note']}")
    if mem.get("last_fan_image_desc"):
        lines.append(
            f"- Last photo HE sent (vision): {mem['last_fan_image_desc'][:280]}"
        )

    return "\n".join(lines)
