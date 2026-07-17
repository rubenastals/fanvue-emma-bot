"""
Lessons store — what the system has learned so far.

Two levels:
- per-fan lessons: ONLY personalizations (his facts, kinks, how HE responds).
  Behavioral rules must NOT live here — Emma's conduct is shared across fans.
- global lessons: pending until approved (or via improve_once --apply-soft).

Both are injected into the reply prompt as compact system blocks.
"""
from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from db import lessons_store

_ROOT = Path(__file__).resolve().parent.parent
_FILE = _ROOT / ".lessons.json"
_LOCK = threading.Lock()

MAX_FAN_LESSONS = 5
MAX_GLOBAL_ACTIVE = 12
MAX_GLOBAL_PENDING = 40

# Personal = facts/prefs about THIS man. Everything else → global behavior.
_PERSONAL = re.compile(
    r"(?i)\b("
    r"this fan|with (?:him|this (?:fan|guy|one))|"
    r"he (?:likes|prefers|responds|hates|loves|is|has|said|mentioned|wants)|"
    r"his (?:name|job|kink|wife|ex|city|kids|age|handle|username)|"
    r"call him|address him as|prefer(?:s)? (?:to be )?called|"
    r"into (?:feet|ass|pussy|custom|videos)|"
    r"divorced|plays football|lives in"
    r")\b"
)
_BEHAVIORAL = re.compile(
    r"(?i)\b("
    r"never |always |do not |don'?t |emma (?:must|should|never)|"
    r"all (?:fans|chats|conversations)|every (?:fan|chat)|"
    r"language|spanglish|nickname|nene|nena|papi|caro|"
    r"claim (?:a |photo|sent|content)|invent (?:content|facts|name)|"
    r"pitch|soft[- ]?sell|hard[- ]?sell|unlock|inbox|bandeja|"
    r"after (?:a )?mistake|build rapport|de-escalate|frustrat|"
    r"mirror (?:his |the )?language|one language|full (?:spanish|english)"
    r")\b"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    return lessons_store.load_bundle()


def _save(data: dict) -> None:
    lessons_store.save_bundle(data)


def _similar(a: str, b: str) -> bool:
    """Cheap dedupe: normalized token overlap."""
    ta = set((a or "").lower().split())
    tb = set((b or "").lower().split())
    if not ta or not tb:
        return False
    overlap = len(ta & tb) / min(len(ta), len(tb))
    return overlap > 0.7


def classify_scope(lesson: str) -> str:
    """
    Return 'fan' only for personalizations about this client.
    Behavioral / sales / language / honesty rules → 'global'.
    Ambiguous defaults to global (shared Emma behavior).
    """
    text = (lesson or "").strip()
    if not text:
        return "global"
    personal = bool(_PERSONAL.search(text))
    behavioral = bool(_BEHAVIORAL.search(text))
    if personal and not behavioral:
        return "fan"
    if personal and behavioral:
        # e.g. "never invent HIS name" → still a global honesty rule
        if re.search(r"(?i)\b(never|always|do not|don'?t|claim|invent)\b", text):
            return "global"
        return "fan"
    return "global"


def add_fan_lesson(fan_uuid: str, lesson: str) -> bool:
    """
    Store a per-fan lesson ONLY if it is personal.
    Misclassified behavioral lessons are routed to global pending.
    """
    lesson = (lesson or "").strip()
    if not lesson or len(lesson) < 10:
        return False
    if classify_scope(lesson) != "fan":
        return propose_global_lesson(lesson, source_fan=fan_uuid[:12])
    with _LOCK:
        data = _load()
        fan_lessons = data["per_fan"].setdefault(fan_uuid, [])
        if any(_similar(lesson, l["text"]) for l in fan_lessons):
            return False
        fan_lessons.append({"text": lesson[:300], "added": _now()})
        data["per_fan"][fan_uuid] = fan_lessons[-MAX_FAN_LESSONS:]
        _save(data)
        return True


def propose_global_lesson(lesson: str, source_fan: str = "") -> bool:
    lesson = (lesson or "").strip()
    if not lesson or len(lesson) < 10:
        return False
    with _LOCK:
        data = _load()
        pool = data["global_active"] + data["global_pending"]
        if any(_similar(lesson, l["text"]) for l in pool):
            return False
        data["global_pending"].append(
            {"text": lesson[:300], "added": _now(), "source_fan": source_fan}
        )
        data["global_pending"] = data["global_pending"][-MAX_GLOBAL_PENDING:]
        _save(data)
    try:
        from core import prompt_audit

        prompt_audit.log_change(
            source="critic",
            action="propose_soft_lesson",
            detail=lesson[:200],
            enters_live_prompt=False,
            meta={"source_fan": source_fan},
        )
    except Exception:
        pass
    return True


def promote_misplaced_fan_lessons() -> Tuple[int, int]:
    """
    Move behavioral lessons stuck in per_fan → global_pending.
    Returns (moved, kept_personal).
    """
    moved = 0
    kept = 0
    with _LOCK:
        data = _load()
        per = data.get("per_fan") or {}
        new_per: Dict[str, list] = {}
        pool = list(data["global_active"] + data["global_pending"])
        for fan_uuid, items in per.items():
            stay = []
            for l in items:
                text = (l.get("text") or "").strip()
                if classify_scope(text) == "fan":
                    stay.append(l)
                    kept += 1
                else:
                    if text and not any(_similar(text, x["text"]) for x in pool):
                        entry = {
                            "text": text[:300],
                            "added": _now(),
                            "source_fan": fan_uuid[:12],
                            "promoted_from_fan": True,
                        }
                        data["global_pending"].append(entry)
                        pool.append(entry)
                        moved += 1
            if stay:
                new_per[fan_uuid] = stay[-MAX_FAN_LESSONS:]
        data["per_fan"] = new_per
        data["global_pending"] = data["global_pending"][-MAX_GLOBAL_PENDING:]
        _save(data)
    return moved, kept


def approve_global(index: int) -> Optional[str]:
    with _LOCK:
        data = _load()
        if not (0 <= index < len(data["global_pending"])):
            return None
        lesson = data["global_pending"].pop(index)
        data["global_active"].append(lesson)
        data["global_active"] = data["global_active"][-MAX_GLOBAL_ACTIVE:]
        _save(data)
        text = lesson["text"]
    try:
        from core import prompt_audit

        prompt_audit.log_change(
            source="operator",
            action="approve_soft_lesson",
            detail=text[:200],
            enters_live_prompt=False,  # still needs INJECT_LESSONS=1
        )
    except Exception:
        pass
    return text


def auto_approve_pending(*, max_n: int = 40) -> List[str]:
    """
    Soft autopilot DISABLED for live quality.

    Pending Soft lessons stay pending for human review on the board / audit log.
    They never auto-activate into global_active (and never enter live prompt).
    """
    pen = pending()[:max_n]
    if pen:
        try:
            from core import prompt_audit

            prompt_audit.log_change(
                source="improve",
                action="soft_held_for_review",
                detail=(
                    f"{len(pen)} Soft lesson(s) held — NOT activated, NOT in live prompt. "
                    f"Sample: {(pen[0].get('text') or '')[:120]}"
                ),
                enters_live_prompt=False,
                meta={"count": len(pen)},
            )
        except Exception:
            pass
    return []  # nothing activated


def reject_global(index: int) -> Optional[str]:
    with _LOCK:
        data = _load()
        if not (0 <= index < len(data["global_pending"])):
            return None
        lesson = data["global_pending"].pop(index)
        _save(data)
        return lesson["text"]


def remove_active(index: int) -> Optional[str]:
    with _LOCK:
        data = _load()
        if not (0 <= index < len(data["global_active"])):
            return None
        lesson = data["global_active"].pop(index)
        _save(data)
        return lesson["text"]


def clear_all_active() -> int:
    """Wipe all active global lessons (emergency quality reset)."""
    with _LOCK:
        data = _load()
        n = len(data.get("global_active") or [])
        data["global_active"] = []
        _save(data)
        return n


def pending() -> List[dict]:
    return _load()["global_pending"]


def active() -> List[dict]:
    return _load()["global_active"]


def render_block(fan_uuid: Optional[str] = None) -> str:
    """Compact prompt block: active global lessons + this fan's personal notes."""
    data = _load()
    bits: List[str] = []
    for l in data["global_active"]:
        bits.append(l["text"])
    if fan_uuid:
        for l in data["per_fan"].get(fan_uuid, []):
            bits.append(f"(this fan only) {l['text']}")
    if not bits:
        return ""
    return "LESSONS LEARNED (apply these):\n" + "\n".join(f"- {b}" for b in bits)
