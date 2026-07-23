"""
Memory callbacks — when Emma brings something up FIRST.

fan_memory stores the card; memory_extractor fills it. This module decides
WHEN to raise his stuff unprompted. Usage state lives in fan_memory (not JSON).
"""
from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from core import fan_memory

MAX_USES_PER_FACT = 3
REPEAT_COOLDOWN_DAYS = 4
SESSION_GAP_MIN = 90
QUIET_TURN_PROB = 0.22


@dataclass
class FactKind:
    name: str
    ripe_after_h: float
    stale_after_h: float
    sensitive: bool = False


_KINDS = {
    "event_soon": FactKind("event_soon", 18, 96),
    "health": FactKind("health", 20, 240, sensitive=True),
    "hardship": FactKind("hardship", 24, 336, sensitive=True),
    "pet": FactKind("pet", 48, 24 * 30),
    "hobby": FactKind("hobby", 36, 24 * 60),
    "work": FactKind("work", 48, 24 * 60),
    "generic": FactKind("generic", 48, 24 * 45),
}

_PATTERNS = [
    (
        "event_soon",
        re.compile(
            r"(?i)\b(interview|exam|test|flight|trip|travel|move|moving|wedding|"
            r"presentation|deadline|surgery|appointment|entrevista|examen|vuelo|viaje|"
            r"mudanza|boda|cita|prueba)\b"
        ),
    ),
    (
        "health",
        re.compile(
            r"(?i)\b(sick|ill|injur\w+|pain|hospital|doctor|recovery|enferm\w+|lesi[oó]n|"
            r"dolor|m[eé]dico|operaci[oó]n)\b"
        ),
    ),
    (
        "hardship",
        re.compile(
            r"(?i)\b(fired|laid off|lost his job|divorce|breakup|broke up|passed away|"
            r"died|funeral|depress\w+|lonely|despid\w+|divorci\w+|ruptura|falleci\w+|"
            r"muri[oó]|solo|deprimid\w+)\b"
        ),
    ),
    ("pet", re.compile(r"(?i)\b(dog|cat|puppy|kitten|pet|perro|gato|mascota)\b")),
    (
        "hobby",
        re.compile(
            r"(?i)\b(gym|guitar|fishing|golf|gaming|game|band|bike|motorcycle|cooking|"
            r"team|football|soccer|basketball|gimnasio|guitarra|pesca|moto|cocina|equipo|"
            r"f[uú]tbol|baloncesto)\b"
        ),
    ),
    (
        "work",
        re.compile(
            r"(?i)\b(work|job|boss|shift|company|business|trabajo|jefe|turno|empresa|negocio)\b"
        ),
    ),
]


def _classify(text: str) -> FactKind:
    for name, rx in _PATTERNS:
        if rx.search(text or ""):
            return _KINDS[name]
    return _KINDS["generic"]


def _fid(text: str) -> str:
    return hashlib.sha256((text or "").strip().lower().encode()).hexdigest()[:12]


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _card_items(mem: dict) -> List[str]:
    items: List[str] = [
        str(f).strip() for f in (mem.get("facts") or []) if str(f).strip()
    ]
    prof = mem.get("profile") or {}
    for k, v in prof.items():
        v = str(v).strip()
        if v and k.lower() not in ("name", "handle", "language", "timezone"):
            items.append(f"{k}: {v}")
    avoid = [str(a).lower() for a in (mem.get("avoid") or []) if str(a).strip()]
    if avoid:
        items = [i for i in items if not any(a in i.lower() for a in avoid)]
    return items


def _eligible(
    item: str, rec: dict, now: datetime, card_at: Optional[datetime]
) -> bool:
    kind = _classify(item)
    uses = int(rec.get("uses", 0))
    if uses >= MAX_USES_PER_FACT:
        return False
    last = _parse(rec.get("last_at"))
    if last and (now - last) < timedelta(days=REPEAT_COOLDOWN_DAYS):
        return False
    if card_at:
        age_h = (now - card_at).total_seconds() / 3600.0
        if age_h < kind.ripe_after_h or age_h > kind.stale_after_h:
            return False
    return True


def pick(
    fan_uuid: str,
    mem: dict,
    *,
    gap_minutes: Optional[float] = None,
    sell_open: bool = False,
    mode: str = "BOND",
    now: Optional[datetime] = None,
    fan_handle: str = "",
) -> Optional[str]:
    """Return a TURN line for one natural callback, or None. Records usage in fan_memory."""
    if not fan_uuid:
        return None
    now = now or datetime.now(timezone.utc)
    items = _card_items(mem)
    if not items:
        return None

    reconnect = gap_minutes is not None and gap_minutes >= SESSION_GAP_MIN
    if not reconnect:
        if mode != "BOND" or random.random() > QUIET_TURN_PROB:
            return None

    usage = fan_memory.get_callback_usage(fan_uuid)
    last_fire = _parse(usage.get("_last_fire_at"))
    if (
        last_fire
        and (now - last_fire) < timedelta(minutes=SESSION_GAP_MIN)
        and not reconnect
    ):
        return None

    card_at = _parse(mem.get("interaction_digest_at")) or _parse(mem.get("first_seen"))

    pool: List[tuple[str, FactKind]] = []
    for it in items:
        kind = _classify(it)
        if kind.sensitive and sell_open:
            continue
        rec = usage.get(_fid(it), {})
        if _eligible(it, rec, now, card_at):
            pool.append((it, kind))
    if not pool:
        return None

    pool.sort(
        key=lambda p: (
            int(usage.get(_fid(p[0]), {}).get("uses", 0)),
            0 if p[1].name == "event_soon" else 1,
            random.random(),
        )
    )
    item, kind = pool[0]
    fact_id = _fid(item)

    fan_memory.record_callback_fire(
        fan_uuid,
        fact_id,
        item,
        fan_handle=fan_handle,
        at=now,
    )
    print(f"   memory-callback: [{kind.name}] {item[:56]!r}")

    if kind.sensitive:
        return (
            f"CALLBACK THIS TURN (warmth only): he told you — {item}. "
            "Ask how he's doing with it, briefly and human, then let him lead. "
            "No selling anywhere near this, no hints, no locks."
        )
    return (
        f"CALLBACK THIS TURN: he told you — {item}. Bring it up yourself, casually, "
        "in your own words (one short line, like a girlfriend who actually listened). "
        "Don't quote the card, don't interrogate, don't stack it with anything else."
    )


def stats(fan_uuid: str) -> dict:
    return fan_memory.callback_stats(fan_uuid)
