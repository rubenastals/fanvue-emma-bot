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
from core import fan_memory
from core.soft_decline import is_broke_soft, is_price_pushback, is_soft_decline
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
    from core.fan_pushback import is_fan_boundary, is_photo_refusal

    boundary_now = is_fan_boundary(low) or is_photo_refusal(low)
    buying = (
        bool(re.search(_BUYING, low) or re.search(_ACCEPT, low))
        and not fan_sent_media
        and not ask_free
        and not missing_free
        and not boundary_now
    )
    want_another = bool(re.search(_WANT_ANOTHER, low))
    horny = bool(re.search(_HORNY, low))
    smalltalk = bool(re.search(_CHILL_ASK, low)) and not buying
    pushback = bool(
        re.search(_FAN_PUSHBACK, low)
        or (re.search(_PRICE_ISSUE, low) and not re.search(_ACCEPT, low))
    )
    broke_soft = is_broke_soft(low)
    heavy_vent = bool(re.search(_HEAVY_VENT, low))
    heated = status in ("warm", "spender", "whale") or msgs >= 6

    chill_until = _parse_iso(mem.get("chill_until"))
    last_purchase = _parse_iso(mem.get("last_purchase_at"))
    last_reject = _parse_iso(mem.get("last_reject_at"))
    last_ppv = _parse_iso(mem.get("last_ppv_at")) or _parse_iso(
        mem.get("last_offer_at")
    )
    # Fanvue tip/gift stubs injected by poller / history converter
    tip_or_gift_now = bool(
        re.search(
            r"\[fan (tipped you|sent you a Fanvue chat gift)",
            fan_message or "",
            re.I,
        )
    )
    price_pushback = is_price_pushback(low)
    recent_reject = bool(
        price_pushback
        or (last_reject and now - last_reject < timedelta(hours=2))
    )

    return TurnFacts(
        free_in_chat=truth.get("free_in_chat"),
        ppv_unpaid=bool(truth.get("ppv_unpaid")),
        cooloff_active=False,  # PPV cooloff removed (Group A)
        chill_window=False,
        recent_purchase=bool(
            tip_or_gift_now
            or (last_purchase and now - last_purchase < timedelta(minutes=45))
        ),
        recent_reject=recent_reject,
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


def _hard_route(
    facts: TurnFacts, mem: dict, *, fan_message: str = ""
) -> Optional[RouteResult]:
    """
    Only Group-B truth gates. No creativity/sell bans (chill, cooloff, broke,
    billing, react-no-pitch, daily cap) — DeepSeek + SIMPLE core own tone.
    """
    now = _now()

    # Tip / chat gift this turn — thank first (beats unpaid-lock nag)
    if re.search(
        r"\[fan (tipped you|sent you a Fanvue chat gift)",
        fan_message or "",
        re.I,
    ):
        facts.hard_pack = "reward_purchase"
        facts.recent_purchase = True
        d = _decision(
            MODE_TEASE,
            "fan tip/gift this turn — reward, no new pitch",
            allow_price=False,
            allow_ppv_talk=False,
            allow_free_tease=False,
        )
        return RouteResult(
            "reward_purchase", d, facts, {"reward_purchase": True}
        )

    # Just unlocked — short thank-you beat only (~8 min). Do NOT hard-lock
    # reward for 45m or long chats can't sell a 2nd lock. (Tips already handled above.)
    last_purchase = _parse_iso((mem or {}).get("last_purchase_at"))
    purchase_thanks = bool(
        last_purchase and (_now() - last_purchase) < timedelta(minutes=8)
    )
    if purchase_thanks and not facts.ppv_unpaid:
        facts.hard_pack = "reward_purchase"
        facts.recent_purchase = True
        d = _decision(
            MODE_TEASE,
            "fresh purchase — reward/thank, no new pitch",
            allow_price=False,
            allow_ppv_talk=False,
            allow_free_tease=False,
        )
        return RouteResult(
            "reward_purchase", d, facts, {"reward_purchase": True}
        )

    # Fan boundary / stop asking pics — bond only, never sell this turn
    from core.fan_pushback import is_fan_boundary as _fan_bnd

    if _fan_bnd(fan_message or "") or (mem or {}).get("fan_boundary_active"):
        facts.hard_pack = "phase_pull"
        d = _decision(
            MODE_TEASE,
            "fan boundary — reconnect, no pic pressure",
            allow_price=False,
            allow_ppv_talk=False,
            allow_free_tease=False,
            max_bubbles=1,
        )
        return RouteResult("phase_pull", d, facts, {"phase_pull": True})

    # He sent a selfie/photo — react to HIS body first, never pitch this turn
    if facts.fan_sent_media:
        facts.hard_pack = "react_fan_media"
        d = _decision(
            MODE_TEASE,
            "fan sent media — react to him, no PPV pitch",
            allow_price=False,
            allow_ppv_talk=False,
            allow_free_tease=False,
        )
        return RouteResult(
            "react_fan_media", d, facts, {"react_fan_media": True}
        )

    # First 1–2 fan messages: warm subscribe welcome — no sell / no free tease
    if (
        facts.msgs <= 2
        and not facts.buying
        and not facts.ask_free
        and not facts.horny
        and not facts.ppv_unpaid
    ):
        facts.hard_pack = "phase_hook"
        d = _decision(
            MODE_TEASE,
            "first messages — welcome vibe, no pitch",
            allow_price=False,
            allow_ppv_talk=False,
            allow_free_tease=False,
            max_bubbles=2,
        )
        return RouteResult("phase_hook", d, facts, {"phase_hook": True})

    # Unpaid lock — never stack a second. Pitch only if he's not friction/cooling.
    if facts.ppv_unpaid:
        from core.chat_heat import explicit_horny_now

        friction = bool(fan_memory.sell_pressure_paused(mem)) and not explicit_horny_now(
            fan_message or ""
        )
        friction = friction or bool(
            facts.pushback_billing
            or facts.broke_soft
            or facts.heavy_vent
            or is_soft_decline(fan_message or "")
            or re.search(
                r"(?i)\b("
                r"spam|insist|pesad|mentir|enfad|cabre|molest|harta|"
                r"deja de|para ya|basta|shut up|enough|"
                r"no (me )?interes|no quiero|caro|expensive|"
                r"masivo|presión|presion|venderme|vender|"
                # Soft decline / not now — stop unlock nag (chase kills conversion)
                r"no,?\s*sorry|not\s+now|maybe\s+later|another\s+moment|"
                r"otro\s+momento|despu[eé]s|later|nah\b|pass\b|"
                r"not\s+so\s+horny|don'?t\s+want\s+to\s+spend|"
                r"spend\s+my\s+money|no\s+money|can'?t\s+afford|"
                r"maybe\s+in\s+another|next\s+time|otro\s+d[ií]a|"
                # Emotional / wants to talk — do NOT nag the unpaid lock
                r"hablar|talk|prefieres\s+hablar|solo\s+vender|only\s+sell|"
                r"qu[eé]\s+te\s+pas|what\s+happened|mam[aá]|familia|family|"
                r"est[aá]s\s+bien|todo\s+bien|te\s+pas[oó]|dif[ií]cil|"
                r"cuento|cu[eé]ntame|tell\s+me"
                r")\b",
                fan_message or "",
            )
            # Bare soft nos
            or bool(
                re.fullmatch(
                    r"(?i)\s*(no|nope|nah|pass|not\s+now|no\s+thanks|no\s+gracias)"
                    r"\s*[.!,]?\s*(sorry)?\s*",
                    fan_message or "",
                )
            )
            # Bare "si/ok/bien" after a check-in — reconnect, don't FOMO the lock
            or bool(
                re.fullmatch(
                    r"(?i)\s*(s[ií]+|ok|okay|bien|yes|yeah|yep|vale)\s*[.!]?\s*",
                    fan_message or "",
                )
            )
        )
        if friction:
            facts.hard_pack = "phase_pull"
            d = _decision(
                MODE_TEASE,
                "unpaid lock exists but fan friction — reconnect, no unlock nag",
                allow_ppv_talk=False,
                allow_price=False,
                allow_free_tease=False,
            )
            return RouteResult(
                "phase_pull", d, facts, {"phase_pull": True, "ppv_unpaid": True}
            )
        facts.hard_pack = "ppv_unpaid"
        d = _decision(
            MODE_TEASE,
            "unpaid PPV still open — soft unlock only, don't stack",
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


def _soft_active(
    facts: TurnFacts, mem: dict, *, fan_message: str = ""
) -> Dict[str, bool]:
    """
    Light intent → pack. No rigid msg ladder / daily sell cap.
    Prefer packs that CAN attach so DeepSeek isn't stuck in flirt-only.
    """
    now = _now()
    active: Dict[str, bool] = {pid: False for pid in packs.priority_order()}
    free_ok = _free_tease_ok(mem, msgs=facts.msgs, now=now)
    never_gifted = facts.frees_done <= 0

    if facts.recent_purchase:
        active["reward_purchase"] = True

    if facts.fan_sent_media:
        active["react_fan_media"] = True

    # Reject / "caro" / can't afford → objection script (beats generic pull).
    # Do NOT sticky-route when he's asking what's in the unpaid lock.
    _ask_lock = bool(
        re.search(
            r"(?i)\b("
            r"how\s+do\s+you\s+look|what\s+do\s+you\s+look\s+like|"
            r"what.?s\s+in\s+(the|that)\s+(photo|pic)|"
            r"what\s+are\s+you\s+wearing|describe\s+(the|that|your)\s+(photo|pic)|"
            r"c[oó]mo\s+(est[aá]s|sales|te\s+ves)|qu[eé]\s+se\s+ve"
            r")\b",
            fan_message or "",
        )
    )
    if is_price_pushback(fan_message or "") and not facts.recent_purchase and not _ask_lock:
        active["price_objection"] = True

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
        # No free tease on first beats — welcome first (ask_free_first steals pack)
    elif facts.horny:
        # Horny THIS message — can close. Heated+msgs alone is NOT a close.
        active["phase_close"] = True
        if never_gifted and free_ok and facts.msgs >= 3:
            active["ask_free_first"] = True
    else:
        # Mid-chat / warm-but-cold text — build desire; do not auto-PPV
        active["phase_pull"] = True
        if never_gifted and free_ok and facts.msgs >= 3:
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

    # Post-tip / post-purchase: reward only — never attach a new lock this turn
    if pack_id == "reward_purchase":
        return _decision(
            MODE_TEASE,
            reason,
            allow_price=False,
            allow_ppv_talk=False,
            allow_free_tease=False,
            max_bubbles=2,
        )

    # Fan selfie/media — heat on HIM, never pitch
    if pack_id == "react_fan_media":
        return _decision(
            MODE_TEASE,
            reason,
            allow_price=False,
            allow_ppv_talk=False,
            allow_free_tease=False,
            max_bubbles=2,
        )

    # Creative packs — CAN sell (Group A pack→price ban removed)
    if pack_id in (
        "escalate_paid",
        "phase_close",
        "lock_now",
        "phase_pull",
        "phase_spiral",
        "tease_heat",
        "phase_reengage",
        "phase_hook",
        "rapport",
        "price_objection",
        "billing_clarify",
        "chill",
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
        # Pull / spiral without buy or horny = tease only (no cold PPV drop)
        if pack_id in ("phase_pull", "phase_spiral", "tease_heat", "rapport") and not (
            facts.buying or facts.horny or facts.ask_free
        ):
            return _decision(
                MODE_TEASE,
                reason,
                allow_price=False,
                allow_free_tease=free_ok,
            )
        # phase_close / lock_now still need a real lean-in this turn
        if pack_id in ("phase_close", "lock_now") and not (
            facts.buying or facts.horny
        ):
            return _decision(
                MODE_TEASE,
                reason + " (no buy/horny — tease, don't attach)",
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

    hard = _hard_route(facts, mem, fan_message=fan_message or "")
    if hard:
        return hard

    active = _soft_active(facts, mem, fan_message=fan_message or "")
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
                    active = _soft_active(
                        facts, mem, fan_message=fan_message or ""
                    )
        except Exception:
            pass

    pack_id = packs.pick_by_priority(active)
    reason = f"pack:{pack_id} via {facts.soft_source}"
    decision = _decision_for_pack(pack_id, facts, mem, reason)
    return RouteResult(pack_id, decision, facts, active)
