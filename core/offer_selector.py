"""
Closed PPV selector.

The model may decide WHEN to sell and choose WHAT to sell, but only from a
whitelist of real, unsent vault photos. It never writes Emma's chat reply.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import config
from core import vault_catalog


@dataclass
class OfferChoice:
    sell_now: bool
    offer: Optional[Dict[str, Any]]
    reason: str
    confidence: float
    source: str


_THEMES = {
    "ass": ("ass", "culo", "booty", "rear", "back", "thong", "arch"),
    "pussy": (
        "pussy",
        "coño",
        "cono",
        "vagina",
        "open legs",
        "spread",
        "fingers",
        "dildo",
        "vibrator",
    ),
    "breasts": ("tits", "tetas", "boobs", "breast", "topless", "nipple", "pechos"),
    "nude": ("nude", "naked", "desnuda", "desnudo"),
    "lingerie": ("lingerie", "underwear", "bragas", "panties"),
}

_DIRECT_BUY = re.compile(
    r"(?i)\b("
    r"unlock|buy|pay|price|how much|cu[aá]nto|precio|ppv|"
    r"show me|quiero ver|m[aá]ndame|m[aá]ndala|env[ií]ame|p[aá]samela|"
    r"dale|venga va|hazlo|video|v[ií]deo|custom|clip"
    r")\b"
)
_REJECT = re.compile(
    r"(?i)\b(no|nah|pass|caro|expensive|too much|later|luego|"
    r"no tengo|sin dinero|broke|not now)\b"
)
# Fan wants the dirtiest / most explicit shot she has (typos: muuy, picate, guarr…)
_MAX_DIRTY = re.compile(
    r"(?i)("
    r"m[aá]s\s+guarr\w*|muy\s+(?:\w+\s+){0,3}guarr\w*|"
    r"lo\s+m[aá]s\s+(guarr\w*|fuerte|picant\w*|picat\w*|expl[ií]cit\w*|sucio|duro)|"
    r"la\s+m[aá]s\s+(guarr\w*|picant\w*|picat\w*|fuerte|expl[ií]cit\w*)|"
    r"m[aá]s\s+picant\w*|m[aá]s\s+picat\w*|algo\s+muy\s+m+\w*\s+guarr|"
    r"dirtiest|nastiest|filthiest|most\s+(dirty|explicit|filthy|hardcore)|"
    r"full\s+nude|todo\s+lo\s+que\s+teng|lo\s+peor\s+que\s+teng|"
    r"abre(te)?\s+(del\s+todo|todo)|spread\s+(wide|everything)"
    r")"
)


def wants_max_dirty(fan_message: str) -> bool:
    return bool(_MAX_DIRTY.search(fan_message or ""))


def _recently_expired(mem: dict, *, minutes: int = 8) -> bool:
    raw = mem.get("last_ppv_expired_at")
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() < minutes * 60
    except (TypeError, ValueError):
        return False


def _blocked(mem: dict) -> set:
    return set(mem.get("sent_media_uuids") or []) | set(
        mem.get("failed_media_uuids") or []
    )


def _recent_reject(mem: dict, *, minutes: int = 90) -> bool:
    raw = mem.get("last_reject_at")
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() < minutes * 60
    except (TypeError, ValueError):
        return False


def _theme_hits(text: str, label: str) -> int:
    text = (text or "").lower()
    label = (label or "").lower()
    score = 0
    for words in _THEMES.values():
        asked = any(w in text for w in words)
        matches = any(w in label for w in words)
        if asked and matches:
            score += 8
    return score


def candidate_offers(
    mem: dict,
    fan_message: str,
    *,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """Rank real unsent paid photos; return a diverse short whitelist."""
    blocked = _blocked(mem)
    items = [
        dict(i)
        for i in vault_catalog.load_items()
        if int(i.get("level") or 0) >= 1
        and float(i.get("price") or 0) > 0
        and i.get("media_uuid") not in blocked
        and i.get("media_uuid_previous") not in blocked
    ]
    if not items:
        return []

    purchases = int(mem.get("purchases") or 0)
    spent = float(mem.get("total_spent") or 0)
    last_level = int(mem.get("last_offer_level") or 0)
    last_price = float(mem.get("last_offer") or 0)
    context = " ".join(
        [
            fan_message or "",
            " ".join(str(x) for x in (mem.get("interests") or [])),
            str(mem.get("summary") or ""),
        ]
    ).lower()
    rejected = _recent_reject(mem)
    max_dirty = wants_max_dirty(fan_message)

    # Hard commercial band: semantics may choose freely inside the correct
    # rung, but cannot jump a brand-new buyer straight to L6/L7 —
    # EXCEPT when he explicitly asks for the dirtiest she has.
    if max_dirty:
        min_level, max_level = 5, 7
    elif rejected and purchases == 0:
        min_level, max_level = 1, max(2, min(3, (last_level - 1) or 2))
    elif purchases == 0 and spent <= 0:
        min_level, max_level = (3, 5) if last_level == 0 else (2, 5)
    elif purchases < 2:
        min_level, max_level = 3, 6
    elif spent < 50:
        min_level, max_level = 4, 7
    else:
        min_level, max_level = 5, 7
    banded = [
        i for i in items if min_level <= int(i.get("level") or 0) <= max_level
    ]
    if not banded and max_dirty:
        # Vault thin at top — take the highest available paid shots
        banded = sorted(
            items, key=lambda i: int(i.get("level") or 0), reverse=True
        )[:limit]
    if banded:
        items = banded

    def score(item: dict) -> float:
        level = int(item.get("level") or 0)
        price = float(item.get("price") or 0)
        label = str(item.get("label") or "")
        value = float(_theme_hits(context, label))

        if max_dirty:
            # He asked for the filthiest — rank by explicitness hard
            value += level * 4.0
            value += float(item.get("score") or 0) * 1.5
            value += min(price, 80) / 15
            return value

        # Commercial ladder: premium first, soften after a recent rejection,
        # escalate after purchases.
        if rejected and purchases == 0:
            target = max(1, min(3, (last_level - 1) if last_level else 2))
            value += 7 - abs(level - target) * 2
            if last_price and price < last_price:
                value += 3
        elif purchases == 0:
            target = 4 if last_level == 0 else min(5, max(3, last_level))
            value += 7 - abs(level - target) * 1.7
        elif purchases < 2:
            target = min(6, max(4, last_level + 1))
            value += 7 - abs(level - target) * 1.5
        else:
            target = 6 if spent < 50 else 7
            value += 7 - abs(level - target) * 1.3

        # Prefer stronger value inside an equally relevant band.
        value += min(price, 60) / 20
        value += float(item.get("score") or 0) / 10
        return value

    ranked = sorted(items, key=score, reverse=True)

    # Preserve relevance but give the selector different levels/vibes to choose.
    out: List[Dict[str, Any]] = []
    seen_labels = set()
    for item in ranked:
        signature = " ".join(str(item.get("label") or "").lower().split()[:2])
        if signature in seen_labels and len(out) >= 4:
            continue
        out.append(item)
        seen_labels.add(signature)
        if len(out) >= limit:
            break
    return out


def _fallback(
    candidates: List[Dict[str, Any]],
    *,
    fan_message: str,
    facts: Any,
    reason: str,
) -> OfferChoice:
    direct = bool(_DIRECT_BUY.search(fan_message or "")) or bool(
        getattr(facts, "buying", False)
    )
    safe = not (
        getattr(facts, "pushback_billing", False)
        or getattr(facts, "broke_soft", False)
        or getattr(facts, "heavy_vent", False)
    )
    sell = bool(candidates) and direct and safe and not _REJECT.search(
        fan_message or ""
    )
    return OfferChoice(
        sell_now=sell,
        offer=candidates[0] if sell else None,
        reason=reason,
        confidence=0.65 if sell else 0.55,
        source="fallback",
    )


def choose_offer(
    mem: dict,
    fan_message: str,
    *,
    history_turns: Optional[List[Dict[str, str]]] = None,
    facts: Any = None,
) -> OfferChoice:
    """
    Decide sell/no-sell and choose one whitelisted item.

    Direct buying intent is guaranteed a real candidate via fallback. Ambiguous
    warm/hot turns are decided by a small JSON call. Invalid UUIDs are rejected.
    """
    candidates = candidate_offers(mem, fan_message)
    if not candidates:
        return OfferChoice(False, None, "paid catalog exhausted", 1.0, "code")

    direct = bool(_DIRECT_BUY.search(fan_message or "")) or bool(
        getattr(facts, "buying", False)
    )
    max_dirty = wants_max_dirty(fan_message)
    if getattr(facts, "pushback_billing", False) or getattr(
        facts, "broke_soft", False
    ) or getattr(facts, "heavy_vent", False):
        return OfferChoice(False, None, "objection/vent: reconnect first", 1.0, "code")
    if _REJECT.search(fan_message or "") and not direct:
        return OfferChoice(False, None, "current message rejects sale", 1.0, "code")
    # Right after a 30m lock vanished — don't drop a random new PPV unless
    # he's clearly asking for content / the dirtiest shot.
    if _recently_expired(mem, minutes=8) and not direct and not max_dirty:
        return OfferChoice(
            False,
            None,
            "lock just expired — reconnect before a new PPV",
            1.0,
            "code",
        )

    if not getattr(config, "OFFER_SELECTOR_AI", True) or not config.DEEPSEEK_API_KEY:
        return _fallback(
            candidates,
            fan_message=fan_message,
            facts=facts,
            reason="selector disabled",
        )

    history = []
    for turn in (history_turns or [])[-12:]:
        role = turn.get("role") or "user"
        content = (turn.get("content") or "").strip()
        if content:
            history.append(f"{role.upper()}: {content[:350]}")

    options = [
        {
            "media_uuid": i["media_uuid"],
            "level": int(i.get("level") or 0),
            "price": float(i.get("price") or 0),
            "label": str(i.get("label") or ""),
        }
        for i in candidates
    ]
    system = (
        "You are a STRICT Fanvue sales controller, not the chatter. "
        "Return ONLY JSON. Decide whether this exact turn is a natural PPV close. "
        "If selling, choose exactly one media_uuid from CANDIDATES. "
        "Never invent a UUID, product, price, video, custom, bundle, or description. "
        "Direct requests for content/price/unlock should sell now. "
        "If he asks for the dirtiest / most explicit / 'más guarro' / 'más picante' "
        "she has, you MUST pick the HIGHEST level (and score) among CANDIDATES — "
        "never a soft L1/L2 lingerie tease when harder options exist. "
        "Smalltalk, emotional disclosure, price rejection, or a cold one-word reply "
        "should reconnect and not sell. "
        "Sexual momentum may sell ONLY if timing feels clearly earned — several hot "
        "exchanges AND he is leaning in hard. A single horny word is not enough. "
        "When in doubt, do NOT sell — warming him up beats a premature pitch. "
        'Schema: {"sell_now":true|false,"media_uuid":"uuid or null",'
        '"reason":"short","confidence":0.0}.'
    )
    user = (
        f"CURRENT FAN MESSAGE:\n{(fan_message or '')[:600]}\n\n"
        f"RECENT CHAT:\n{chr(10).join(history)[:3500] or '(none)'}\n\n"
        f"CLIENT STATE: messages={int(mem.get('messages') or 0)}, "
        f"purchases={int(mem.get('purchases') or 0)}, "
        f"spent={float(mem.get('total_spent') or 0):.0f}, "
        f"interests={mem.get('interests') or []}, "
        f"last_offer_level={int(mem.get('last_offer_level') or 0)}, "
        f"wants_max_dirty={max_dirty}, "
        f"recent_reject={_recent_reject(mem)}\n\n"
        f"CANDIDATES:\n{json.dumps(options, ensure_ascii=False)}"
    )
    client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url=config.DEEPSEEK_BASE_URL,
    )
    kwargs: Dict[str, Any] = {
        "model": getattr(config, "OFFER_SELECTOR_MODEL", None)
        or getattr(config, "OFFER_SELECTOR_MODEL", None)
        or getattr(config, "DEEPSEEK_FAST_MODEL", None)
        or config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 180,
    }
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    started = time.monotonic()
    try:
        response = client.chat.completions.create(**kwargs)
        raw = (response.choices[0].message.content or "").strip()
        match = re.search(r"\{[\s\S]*\}", raw)
        data = json.loads(match.group(0)) if match else {}
    except Exception as exc:
        print(f"   selector failed: {type(exc).__name__}: {exc}")
        return _fallback(
            candidates,
            fan_message=fan_message,
            facts=facts,
            reason="selector API/JSON failure",
        )

    by_uuid = {i["media_uuid"]: i for i in candidates}
    sell_now = data.get("sell_now") is True
    media_uuid = str(data.get("media_uuid") or "").strip()
    chosen = by_uuid.get(media_uuid)
    reason = str(data.get("reason") or "no reason")[:160]
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence") or 0)))
    except (TypeError, ValueError):
        confidence = 0.0

    # Direct ask must close if inventory exists. Invalid model choices are never
    # trusted; fallback chooses the top real candidate.
    if sell_now and chosen is None:
        return _fallback(
            candidates,
            fan_message=fan_message,
            facts=facts,
            reason="selector returned invalid/non-whitelisted UUID",
        )
    if direct and not sell_now:
        chosen = candidates[0]
        sell_now = True
        reason = f"direct buy override; selector said: {reason}"
        confidence = max(confidence, 0.9)

    # Max-dirty ask: never keep a soft L1/L2 if harder candidates exist
    if sell_now and max_dirty and candidates:
        best = max(
            candidates,
            key=lambda i: (
                int(i.get("level") or 0),
                float(i.get("score") or 0),
                float(i.get("price") or 0),
            ),
        )
        if chosen is None or (
            int(chosen.get("level") or 0) < 5 and int(best.get("level") or 0) >= 5
        ):
            chosen = best
            sell_now = True
            reason = f"max-dirty override → L{best.get('level')} {str(best.get('label') or '')[:40]}"
            confidence = max(confidence, 0.9)

    elapsed = time.monotonic() - started
    print(
        f"   selector: sell={sell_now} conf={confidence:.2f} "
        f"source=ai +{elapsed:.1f}s reason={reason[:80]}"
    )
    return OfferChoice(
        sell_now=sell_now,
        offer=chosen if sell_now else None,
        reason=reason,
        confidence=confidence,
        source="ai",
    )
