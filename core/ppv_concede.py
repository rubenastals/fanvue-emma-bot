"""
Defend expensive unpaid PPV for a few turns, then concede to a cheaper lock.

Flow (code-owned):
  unpaid expensive lock + fan asks cheaper
    → hits 1..N: DEFEND (hold price, no new attach)
    → hits > N:  CONCEDE (unsend expensive → attach L1–L2 cheaper)

Already-cheap locks (< threshold) skip this FSM — just push unlock.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config import config
from core import fan_memory, offer_selector, vault_catalog

# Fan wants a lower price / cheaper alt while a lock is open
_ASK_CHEAPER = re.compile(
    r"(?i)("
    r"\b("
    r"m[aá]s\s+barat\w*|barat[oa]s?|"
    r"cheaper|too\s+(?:expensive|much)|"
    r"muy\s+caro|demasiado\s+caro|es\s+caro|est[aá]\s+caro|"
    r"pero\s+es\s+caro|caro|expensive|"
    r"baja(r)?\s+(?:el\s+)?precio|descuento|discount|"
    r"no\s+puedo\s+(?:pagar\w*|eso|permit\w*)|menos\s+caro|"
    r"algo\s+m[aá]s\s+barat|otra\s+m[aá]s\s+barat|"
    r"one\s+cheaper|lower\s+(?:the\s+)?price|"
    r"half\s+price|rebaja|taca[nñ]o|no\s+llego|"
    r"muy\s+alto|me\s+pasa\s+de"
    r")\b|"
    # "por 5", "$5", "a 5 euros", "5 dólares"
    r"(?:^|[^\d])(?:\$|€)?\s*([1-9]|1[0-4])(?:\s*(?:\$|€|eur|euros?|d[oó]lares?|bucks?))?(?:[^\d]|$)|"
    r"\bpor\s+([1-9]|1[0-4])\b"
    r")"
)

# He's buying / unlocking the CURRENT lock — never unsend in that case
_BUYING_CURRENT = re.compile(
    r"(?i)\b("
    r"la\s+compro|lo\s+compro|te\s+lo\s+pago|te\s+la\s+pago|"
    r"ya\s+la\s+(?:abro|pago|compro)|unlock|desbloqueo|"
    r"ok\s+la\s+quiero|vale\s+la\s+quiero|me\s+la\s+quedo|"
    r"i(?:'?ll| will)\s+(?:buy|unlock|pay)|buying\s+it"
    r")\b"
)

PHASE_NONE = "none"
PHASE_DEFEND = "defend"
PHASE_CONCEDE = "concede"


@dataclass
class ConcedePlan:
    phase: str
    hits: int
    reason: str
    lock_price: float = 0.0
    msg_uuid: str = ""
    cheap_offer: Optional[Dict[str, Any]] = None


def fan_asks_cheaper(fan_message: str) -> bool:
    return bool(_ASK_CHEAPER.search(fan_message or ""))


def fan_buying_current(fan_message: str) -> bool:
    return bool(_BUYING_CURRENT.search(fan_message or ""))


def _defend_hits_needed(mem: Optional[dict] = None) -> int:
    """
    How many cheaper-asks to DEFEND before conceding (default 2).

    Bruised $0 fans (already rejected / pitched high) get 1 defend only —
    they already proved they won't eat $40.
    """
    base = max(1, int(getattr(config, "PPV_PRICE_DEFEND_HITS", 2) or 2))
    if mem is not None:
        try:
            from core.offer_selector import _price_bruised, _zero_spender

            if _zero_spender(mem) and _price_bruised(mem):
                return 1
        except Exception:
            pass
    return base


def _min_expensive() -> float:
    """Locks at/above this price are eligible for defend→concede."""
    return float(getattr(config, "PPV_CONCEDE_MIN_PRICE", 15) or 15)


def lock_price(ppv_status: Optional[dict], mem: dict) -> float:
    if ppv_status and ppv_status.get("price") is not None:
        try:
            return float(ppv_status.get("price") or 0)
        except (TypeError, ValueError):
            pass
    try:
        return float(mem.get("last_ppv_price") or mem.get("last_offer") or 0)
    except (TypeError, ValueError):
        return 0.0


def lock_message_uuid(ppv_status: Optional[dict], mem: dict) -> str:
    for src in (ppv_status or {}, mem):
        uid = (src.get("message_uuid") or src.get("last_ppv_message_uuid") or "").strip()
        if uid:
            return uid
    return ""


def _concede_blocked_uuids(mem: dict) -> set:
    """
    UUIDs to skip when picking a concede alt.

    sent_media_uuids = seen only (free / purchased). Unpaid pitches are not
    in that set. Still skip the currently open expensive lock.
    """
    blocked = set(mem.get("sent_media_uuids") or [])
    if mem.get("last_ppv_media_uuid"):
        blocked.add(str(mem["last_ppv_media_uuid"]))
    return blocked


def pick_cheaper_offer(
    mem: dict,
    *,
    current_price: float,
    fan_message: str = "",
    history_turns: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Cheapest L1–L2 (or soft L3) under the active lock price."""
    blocked = _concede_blocked_uuids(mem)
    # Prefer fresh candidates from selector, then raw vault
    cands = offer_selector.candidate_offers(
        mem, fan_message or "algo más barato", history_turns=history_turns
    )
    under = [
        i
        for i in cands
        if int(i.get("level") or 0) <= 2
        and 0 < float(i.get("price") or 0) < max(current_price, 0.01)
        and float(i.get("price") or 0) < 15
        and i.get("media_uuid") not in blocked
        and i.get("media_uuid_previous") not in blocked
    ]
    if not under:
        try:
            items = [dict(i) for i in vault_catalog.load_items()]
        except Exception:
            items = []
        under = [
            i
            for i in items
            if int(i.get("level") or 0) in (1, 2)
            and 0 < float(i.get("price") or 0) < max(current_price, 0.01)
            and i.get("media_uuid") not in blocked
            and i.get("media_uuid_previous") not in blocked
        ]
    # Soft L3 under $15 if lingerie/topless fully exhausted even for repost
    if not under:
        try:
            items = [dict(i) for i in vault_catalog.load_items()]
        except Exception:
            items = []
        under = [
            i
            for i in items
            if int(i.get("level") or 0) == 3
            and 0 < float(i.get("price") or 0) < min(15.0, max(current_price, 0.01))
            and i.get("media_uuid") not in blocked
            and i.get("media_uuid_previous") not in blocked
        ]
    if not under:
        return None
    return min(
        under,
        key=lambda i: (float(i.get("price") or 0), int(i.get("level") or 0)),
    )


def evaluate(
    *,
    mem: dict,
    fan_message: str,
    unpaid: bool,
    ppv_status: Optional[dict] = None,
    history_turns: Optional[List[Dict[str, Any]]] = None,
) -> ConcedePlan:
    """
    Pure decision (no I/O aside from catalog read for concede offer).

    Does NOT bump hits — caller persists via bump_defend_hits / mark_conceded.
    """
    if not unpaid:
        return ConcedePlan(PHASE_NONE, 0, "no unpaid lock")
    if fan_buying_current(fan_message):
        return ConcedePlan(
            PHASE_NONE,
            int(mem.get("price_defend_hits") or 0),
            "fan buying current lock — do not unsend",
        )
    if not fan_asks_cheaper(fan_message):
        return ConcedePlan(
            PHASE_NONE,
            int(mem.get("price_defend_hits") or 0),
            "not a cheaper ask",
        )

    price = lock_price(ppv_status, mem)
    if price < _min_expensive():
        return ConcedePlan(
            PHASE_NONE,
            int(mem.get("price_defend_hits") or 0),
            f"lock already cheap (${price:.0f})",
            lock_price=price,
        )
    if mem.get("price_concede_done"):
        return ConcedePlan(
            PHASE_NONE,
            int(mem.get("price_defend_hits") or 0),
            "already conceded this lock episode",
            lock_price=price,
        )

    prior = int(mem.get("price_defend_hits") or 0)
    hits = prior + 1
    msg_uuid = lock_message_uuid(ppv_status, mem)
    need = _defend_hits_needed(mem)

    # Still inside defend window
    if hits <= need:
        return ConcedePlan(
            PHASE_DEFEND,
            hits,
            f"defend ${price:.0f} ({hits}/{need})",
            lock_price=price,
            msg_uuid=msg_uuid,
        )

    cheap = pick_cheaper_offer(
        mem,
        current_price=price,
        fan_message=fan_message,
        history_turns=history_turns,
    )
    if not cheap:
        return ConcedePlan(
            PHASE_DEFEND,
            hits,
            f"concede wanted but no cheaper inventory — keep defending ${price:.0f}",
            lock_price=price,
            msg_uuid=msg_uuid,
        )
    if not msg_uuid:
        return ConcedePlan(
            PHASE_DEFEND,
            hits,
            "concede wanted but no message_uuid to unsend — keep defending",
            lock_price=price,
        )

    return ConcedePlan(
        PHASE_CONCEDE,
        hits,
        (
            f"concede ${price:.0f} → L{cheap.get('level')} "
            f"${float(cheap.get('price') or 0):.0f}"
        ),
        lock_price=price,
        msg_uuid=msg_uuid,
        cheap_offer=cheap,
    )


def bump_defend_hits(fan_uuid: str, *, fan_handle: str = "", hits: int) -> int:
    return fan_memory.set_price_defend_hits(
        fan_uuid, hits=hits, fan_handle=fan_handle
    )


def mark_conceded(fan_uuid: str, *, fan_handle: str = "") -> None:
    fan_memory.mark_price_conceded(fan_uuid, fan_handle=fan_handle)
