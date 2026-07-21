"""
Intent router — HardGates (code) → SoftClassify → one winning pack.

Does not write Emma's words. Only picks pack_id + TurnDecision flags.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from core import packs
from core.turn_facts import TurnFacts
from core.turn_policy import (
    MODE_HARD_SELL,
    MODE_SOFT_SELL,
    MODE_TEASE,
    TurnDecision,
    _ACCEPT,
    _ASK_FREE,
    _BROKE_SOFT,
    _BUYING,
    _CHILL_ASK,
    _FAN_PUSHBACK,
    _FAN_SENT_MEDIA,
    _HEAVY_VENT,
    _HORNY,
    _MISSING_DELIVERY,
    _PRICE_ISSUE,
    _WANT_ANOTHER,
    _free_tease_ok,
)


@dataclass
class RouteResult:
    pack_id: str
    decision: TurnDecision
    facts: TurnFacts
    active: Dict[str, bool]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def build_facts(
    mem: dict,
    fan_message: str,
    *,
    delivery_truth: Optional[dict] = None,
) -> TurnFacts:
    text = (fan_message or "").strip()
    low = text.lower()
    truth = delivery_truth or {}
    now = _now()
    msgs = int(mem.get("messages") or 0)
    status = mem.get("status") or "new"
    spent = float(mem.get("total_spent") or 0)
    frees_done = int(mem.get("free_teases_sent") or 0)

    fan_sent_media = bool(re.search(_FAN_SENT_MEDIA, low))
    ask_free = bool(re.search(_ASK_FREE, low)) and not fan_sent_media
    missing = bool(re.search(_MISSING_DELIVERY, low)) and not fan_sent_media
    missing_free = missing and bool(
        re.search(r"\b(gratis|grastis|gratiz|free)\b", low)
    )
    buying = (
        bool(re.search(_BUYING, low) or re.search(_ACCEPT, low))
        and not fan_sent_media
        and not ask_free
        and not missing_free
    )
    want_another = bool(re.search(_WANT_ANOTHER, low))
    horny = bool(re.search(_HORNY, low))
    smalltalk = bool(re.search(_CHILL_ASK, low)) and not buying
    pushback = bool(
        re.search(_FAN_PUSHBACK, low)
        or (re.search(_PRICE_ISSUE, low) and not re.search(_ACCEPT, low))
    )
    broke_soft = bool(re.search(_BROKE_SOFT, low))
    heavy_vent = bool(re.search(_HEAVY_VENT, low))
    heated = status in ("warm", "spender", "whale") or msgs >= 6

    chill_until = _parse_iso(mem.get("chill_until"))
    last_purchase = _parse_iso(mem.get("last_purchase_at"))
    last_reject = _parse_iso(mem.get("last_reject_at"))
    last_ppv = _parse_iso(mem.get("last_ppv_at")) or _parse_iso(
        mem.get("last_offer_at")
    )

    return TurnFacts(
        free_in_chat=truth.get("free_in_chat"),
        ppv_unpaid=bool(truth.get("ppv_unpaid")),
        cooloff_active=False,  # PPV cooloff removed (Group A)
        chill_window=False,
        recent_purchase=bool(
            last_purchase and now - last_purchase < timedelta(minutes=45)
        ),
        recent_reject=False,
        fan_sent_media=fan_sent_media,
        ask_free=ask_free,
        missing_delivery=missing,
        missing_free=missing_free,
        buying=buying,
        want_another=want_another,
        horny=horny,
        smalltalk=smalltalk,
        pushback_billing=pushback,
        broke_soft=broke_soft,
        heavy_vent=heavy_vent,
        heated=heated,
        msgs=msgs,
        frees_done=frees_done,
        status=status,
        spent=spent,
        soft_source="regex",
    )


def _decision(
    mode: str,
    reason: str,
    *,
    allow_price: bool = False,
    allow_ppv_talk: bool = True,
    allow_free_tease: bool = False,
    max_bubbles: int = 2,
) -> TurnDecision:
    return TurnDecision(
        mode=mode,
        reason=reason,
        max_bubbles=max_bubbles,
        allow_ppv_talk=allow_ppv_talk,
        allow_price=allow_price,
        allow_free_tease=allow_free_tease,
    )


def _hard_route(facts: TurnFacts, mem: dict) -> Optional[RouteResult]:
    """
    Only Group-B truth gates. No creativity/sell bans (chill, cooloff, broke,
    billing, react-no-pitch, daily cap) — DeepSeek + SIMPLE core own tone.
    """
    now = _now()

    # Unpaid lock — ALWAYS push that unlock. Never stack a second (even if
    # he says "manda/buy/video" — that means open the waiting lock, not invent).
    if facts.ppv_unpaid:
        facts.hard_pack = "ppv_unpaid"
        d = _decision(
            MODE_TEASE,
            "unpaid PPV still open — push unlock, don't stack another",
            allow_ppv_talk=True,
            allow_price=False,
        )
        return RouteResult("ppv_unpaid", d, facts, {"ppv_unpaid": True})

    # Free already in chat
    if (facts.missing_free or facts.ask_free) and facts.free_in_chat is True:
        facts.hard_pack = "delivery_scroll"
        d = _decision(
            MODE_TEASE,
            "API: free already in chat — tell him to scroll up",
            allow_ppv_talk=True,
            allow_price=False,
        )
        return RouteResult(
            "delivery_scroll", d, facts, {"delivery_scroll": True}
        )

    # Missing free + API says not in chat → recover L0
    if facts.missing_free and facts.free_in_chat is False:
        if _free_tease_ok(mem, msgs=facts.msgs, now=now, missing_unverified=True):
            facts.hard_pack = "delivery_missing"
            d = _decision(
                MODE_TEASE,
                "missing free + API not in chat — recover L0",
                allow_ppv_talk=False,
                allow_price=False,
                allow_free_tease=True,
            )
            return RouteResult(
                "delivery_missing", d, facts, {"delivery_missing": True}
            )

    # Ghost free / missing delivery while API says no free
    if facts.missing_delivery and facts.free_in_chat is False:
        facts.hard_pack = "delivery_missing"
        if facts.frees_done >= 1:
            d = _decision(
                MODE_SOFT_SELL,
                "fan expects delivery — attach real PPV",
                allow_price=True,
            )
            return RouteResult(
                "delivery_missing", d, facts, {"delivery_missing": True}
            )
        if _free_tease_ok(mem, msgs=facts.msgs, now=now, missing_unverified=True):
            d = _decision(
                MODE_TEASE,
                "missing delivery — recover L0",
                allow_free_tease=True,
                allow_price=False,
            )
            return RouteResult(
                "delivery_missing", d, facts, {"delivery_missing": True}
            )
        d = _decision(
            MODE_SOFT_SELL,
            "fan expects a delivery — attach real PPV",
            allow_price=True,
        )
        return RouteResult(
            "delivery_missing", d, facts, {"delivery_missing": True}
        )

    return None


def _soft_active(facts: TurnFacts, mem: dict) -> Dict[str, bool]:
    """
    Light intent → pack. No rigid msg ladder / daily sell cap.
    Prefer packs that CAN attach so DeepSeek isn't stuck in flirt-only.
    """
    now = _now()
    active: Dict[str, bool] = {pid: False for pid in packs.priority_order()}
    free_ok = _free_tease_ok(mem, msgs=facts.msgs, now=now)
    never_gifted = facts.frees_done <= 0

    if facts.ask_free and facts.frees_done >= 1:
        active["escalate_paid"] = True
        active["phase_close"] = True
    elif facts.ask_free and _free_tease_ok(
        mem, msgs=facts.msgs, now=now, force_ask=True
    ):
        active["ask_free_first"] = True
    elif facts.ask_free:
        active["phase_close"] = True

    if facts.missing_delivery and not facts.ppv_unpaid:
        active["delivery_missing"] = True

    if facts.buying and not facts.ask_free:
        active["phase_close"] = True
        active["lock_now"] = True
    elif facts.msgs < 3 and not facts.horny and not facts.buying:
        active["phase_hook"] = True
        if free_ok:
            active["ask_free_first"] = True
    elif facts.horny or (facts.heated and facts.msgs >= 8):
        # Genuinely hot — can close
        active["phase_close"] = True
        if never_gifted and free_ok:
            active["ask_free_first"] = True
    else:
        # Mid-chat without strong buy/heat signal — build desire first
        active["phase_pull"] = True
        if never_gifted and free_ok:
            active["ask_free_first"] = True

    if not any(active.values()):
        active["phase_pull"] = True

    return active


def _decision_for_pack(
    pack_id: str, facts: TurnFacts, mem: dict, reason: str
) -> TurnDecision:
    now = _now()
    free_ok = _free_tease_ok(mem, msgs=facts.msgs, now=now)

    # Truth-only packs (no new paid lock)
    if pack_id == "ppv_unpaid":
        return _decision(MODE_TEASE, reason, allow_price=False)
    if pack_id == "delivery_scroll":
        return _decision(MODE_TEASE, reason, allow_price=False)
    if pack_id == "ask_free_first":
        return _decision(
            MODE_TEASE, reason, allow_price=False, allow_free_tease=True
        )
    if pack_id == "delivery_missing":
        if facts.frees_done >= 1:
            return _decision(MODE_SOFT_SELL, reason, allow_price=True)
        if _free_tease_ok(mem, msgs=facts.msgs, now=now, missing_unverified=True):
            return _decision(
                MODE_TEASE, reason, allow_free_tease=True, allow_price=False
            )
        return _decision(MODE_SOFT_SELL, reason, allow_price=True)

    # Creative packs — CAN sell (Group A pack→price ban removed)
    if pack_id in (
        "escalate_paid",
        "phase_close",
        "lock_now",
        "phase_pull",
        "phase_spiral",
        "tease_heat",
        "phase_reengage",
        "react_fan_media",
        "phase_hook",
        "rapport",
        "price_objection",
        "billing_clarify",
        "chill",
        "reward_purchase",
        "post_sale_withdrawal",
    ):
        mode = MODE_SOFT_SELL
        if facts.buying and (
            facts.status in ("spender", "whale") or facts.spent > 0
        ):
            mode = MODE_HARD_SELL
        elif pack_id in ("phase_hook", "rapport") and facts.msgs < 4 and not facts.buying:
            return _decision(
                MODE_TEASE,
                reason,
                allow_price=False,
                allow_free_tease=free_ok,
            )
        return _decision(
            mode,
            reason,
            allow_price=True,
            allow_free_tease=free_ok and not facts.buying,
        )
    return _decision(
        MODE_SOFT_SELL, reason, allow_price=True, allow_free_tease=free_ok
    )


def decision_for_pack(
    pack_id: str, facts: TurnFacts, mem: dict, reason: str
) -> TurnDecision:
    """Public: map pack_id → TurnDecision flags."""
    return _decision_for_pack(pack_id, facts, mem, reason)


def is_ambiguous(facts: TurnFacts, active: Dict[str, bool]) -> bool:
    """True when multiple soft packs compete or no clear intent."""
    soft_hits = [
        k
        for k, v in active.items()
        if v
        and k
        not in (
            "chill",
            "delivery_scroll",
            "delivery_missing",
            "ppv_unpaid",
            "react_fan_media",
            "billing_clarify",
        )
    ]
    if len(soft_hits) >= 3:
        return True
    # Message short / unclear and no strong intent
    strong = facts.ask_free or facts.buying or facts.horny or facts.missing_delivery
    if not strong and facts.msgs >= 4 and not facts.smalltalk:
        return True
    return False


def route(
    mem: dict,
    fan_message: str,
    *,
    delivery_truth: Optional[dict] = None,
    history_snippets: Optional[List[str]] = None,
) -> RouteResult:
    """
    Full route: hard gates first, then soft flags → one pack.
    Optional SoftClassify JSON when ambiguous and SOFT_CLASSIFY=1.
    """
    facts = build_facts(mem, fan_message, delivery_truth=delivery_truth)

    hard = _hard_route(facts, mem)
    if hard:
        return hard

    active = _soft_active(facts, mem)
    facts.ambiguous = is_ambiguous(facts, active)

    # Optional JSON classifier
    try:
        from config import config as _cfg

        soft_on = bool(getattr(_cfg, "SOFT_CLASSIFY", False))
    except Exception:
        soft_on = False

    if soft_on and facts.ambiguous:
        try:
            from core import soft_classify

            hint = soft_classify.classify(
                fan_message,
                history_snippets=history_snippets or [],
                facts=facts,
            )
            if hint:
                facts.soft_source = "json"
                # Apply pack_hint as exclusive soft winner when valid
                pid = (hint.get("pack_hint") or "").strip()
                if pid in packs.list_pack_ids():
                    for k in list(active.keys()):
                        active[k] = False
                    active[pid] = True
                for key in (
                    "ask_free",
                    "missing_delivery",
                    "buying",
                    "horny",
                    "smalltalk",
                    "pushback_billing",
                    "want_another",
                ):
                    if key in hint and isinstance(hint[key], bool):
                        setattr(facts, key, hint[key])
                # Rebuild soft from updated facts if no pack_hint
                if not pid:
                    active = _soft_active(facts, mem)
        except Exception:
            pass

    pack_id = packs.pick_by_priority(active)
    reason = f"pack:{pack_id} via {facts.soft_source}"
    decision = _decision_for_pack(pack_id, facts, mem, reason)
    return RouteResult(pack_id, decision, facts, active)
