"""
Lessons store — what the system has learned so far.

Two levels:
- per-fan lessons: auto-applied (low risk, scoped to one fan)
- global lessons: PENDING until approved by the operator
  (scripts/review_lessons.py) so the base behavior never drifts silently.

Both are injected into the reply prompt as compact system blocks.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from db import lessons_store

_ROOT = Path(__file__).resolve().parent.parent
_FILE = _ROOT / ".lessons.json"
_LOCK = threading.Lock()

MAX_FAN_LESSONS = 5
MAX_GLOBAL_ACTIVE = 10
MAX_GLOBAL_PENDING = 25


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


def add_fan_lesson(fan_uuid: str, lesson: str) -> bool:
    lesson = (lesson or "").strip()
    if not lesson or len(lesson) < 10:
        return False
    with _LOCK:
        data = _load()
        lessons = data["per_fan"].setdefault(fan_uuid, [])
        if any(_similar(lesson, l["text"]) for l in lessons):
            return False
        lessons.append({"text": lesson[:300], "added": _now()})
        data["per_fan"][fan_uuid] = lessons[-MAX_FAN_LESSONS:]
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
        return True


def approve_global(index: int) -> Optional[str]:
    with _LOCK:
        data = _load()
        if not (0 <= index < len(data["global_pending"])):
            return None
        lesson = data["global_pending"].pop(index)
        data["global_active"].append(lesson)
        data["global_active"] = data["global_active"][-MAX_GLOBAL_ACTIVE:]
        _save(data)
        return lesson["text"]


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


def pending() -> List[dict]:
    return _load()["global_pending"]


def active() -> List[dict]:
    return _load()["global_active"]


def render_block(fan_uuid: Optional[str] = None) -> str:
    """Compact prompt block: active global lessons + this fan's lessons."""
    data = _load()
    bits: List[str] = []
    for l in data["global_active"]:
        bits.append(l["text"])
    if fan_uuid:
        for l in data["per_fan"].get(fan_uuid, []):
            bits.append(f"(this fan) {l['text']}")
    if not bits:
        return ""
    return "LESSONS LEARNED (apply these):\n" + "\n".join(f"- {b}" for b in bits)
