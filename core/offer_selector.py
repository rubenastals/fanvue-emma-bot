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

# Clear ask for THIS photo — keep narrow so "dale/video" don't force random PPVs
_DIRECT_BUY = re.compile(
    r"(?i)\b("
    r"unlock|buy|pay|"
    # "how much time?" must NOT match — only price asks
    r"how\s+much\s+(is|does|do|for|to)|"
    r"cu[aá]nto\s+(cuesta|cuesta|es|vale)|precio|"
    r"show me|let me see|quiero ver(la|lo)?|"
    r"m[aá]nda(me|la|mela)|env[ií]a(me|la|mela)|p[aá]sa(me|la|mela)|"
    r"ense[nñ]?[aá](me|mela|rmela)?|muestr[aá](me|mela)|"  # eseñame typo OK
    r"por\s*favor|please|"
    r"no\s+me\s+dejes(\s+con)?"
    r")\b"
)
# Clarifying her content / cold check-ins — NEVER a PPV close
_CLARIFY_NO_SELL = re.compile(
    r"(?i)("
    r"^\s*(pero\s+)?(fotos?|pics?|photos?)\s+para\s+m[ií]\s*\??\s*$|"
    r"^\s*a\s+grabar\s*\??\s*$|"
    r"^\s*c[oó]mo\s*\??\s*$|"
    r"^\s*(s[ií]+|ok|okay|bien|yes|yeah)\s*[.!]?\s*$|"
    r"no\s+te\s+ibas\s+a\s+grabar|"
    r"prefieres\s+hablar|solo\s+vender|only\s+sell|"
    r"qu[eé]\s+te\s+pas[oó]|what\s+happened"
    r")"
)
# NEVER bare \bno\b — matches "no me dejes con las ganas" and kills closes
_REJECT = re.compile(
    r"(?i)\b("
    r"nah|pass|caro|expensive|too much|later|luego|"
    r"no\s+gracias|no\s+quiero|no\s+me\s+interesa|"
    r"not\s+now|no\s+tengo|sin\s+dinero|broke|"
    r"maybe\s+later|otro\s+d[ií]a|despu[eé]s"
    r")\b"
)
# Fan wants the dirtiest / most explicit shot she has (typos: muuy, picate, guarr…)
_MAX_DIRTY = re.compile(
    r"(?i)("
    r"m[aá]s\s+guarr\w*|muy\s+(?:\w+\s+){0,3}guarr\w*|"
    r"lo\s+m[aá]s\s+(guarr\w*|fuerte|picant\w*|picat\w*|expl[ií]cit\w*|sucio|duro)|"
    r"la\s+m[aá]s\s+(guarr\w*|picant\w*|picat\w*|fuerte|expl[ií]cit\w*)|"
    r"m[aá]s\s+picant\w*|m[aá]s\s+picat\w*|algo\s+muy\s+m+\w*\s+guarr|"
    r"como\s+de\s+guarr|how\s+dirty|qué\s+tan\s+guarr|"
    r"dirtiest|nastiest|filthiest|most\s+(dirty|explicit|filthy|hardcore)|"
    r"full\s+nude|todo\s+lo\s+que\s+teng|lo\s+peor\s+que\s+teng|"
    r"abre(te)?\s+(del\s+todo|todo)|spread\s+(wide|everything)"
    r")"
)

# Emma already framed the next shot as filthiest / masturbation beat
_EMMA_PROMISED_DIRTY = re.compile(
    r"(?i)("
    r"la\s+m[aá]s\s+guarr|lo\s+m[aá]s\s+guarr|"
    r"s[uú]per\s+guarr|super\s+guarr|muy\s+muy\s+guarr|"
    r"toc[aá]ndome|pensando\s+en\s+tu\s+polla|"
    r"gemir\s+tu\s+nombre|hasta\s+gemir|"
    r"touching\s+myself|dirtiest|filthiest|"
    r"la\s+m[aá]s\s+(sucia|expl[ií]cita|fuerte)"
    r")"
)

# She stalled with "ask nicely / I'll send it" — next comply must CLOSE
_EMMA_OWED_SEND = re.compile(
    r"(?i)("
    r"p[ií]demela\s+bien|ask\s+me\s+nicely|"
    r"te\s+la\s+(mando|env[ií]o|bloqueo|muestro)|"
    r"i'?ll\s+(send|lock|drop)\s+it|"
    r"quieres\s+verla|te\s+da\s+miedo"
    r")"
)

_COMPLY_AFTER_STALL = re.compile(
    r"(?i)\b("
    r"por\s*favor|please|vale|ok|okay|dale|venga|"
    r"s[ií]+|ense[nñ]|manda|env[ií]|pasa|quiero|"
    r"ganas|gatas|hazlo|vamos"
    r")\b"
)


def wants_max_dirty(fan_message: str) -> bool:
    return bool(_MAX_DIRTY.search(fan_message or ""))


def _recent_assistant_text(
    history_turns: Optional[List[Dict[str, str]]], *, n: int = 6
) -> str:
    chunks: List[str] = []
    for turn in (history_turns or [])[-n:]:
        if (turn.get("role") or "") != "assistant":
            continue
        content = (turn.get("content") or "").strip()
        if content:
            chunks.append(content)
    return "\n".join(chunks)


def context_wants_max_dirty(
    fan_message: str,
    history_turns: Optional[List[Dict[str, str]]] = None,
) -> bool:
    """
    Max-dirty band if HE asks for it, OR Emma already promised the filthiest
    shot in recent turns (so 'enseñamela' after 'la más guarra' cannot land L2).
    """
    if wants_max_dirty(fan_message):
        return True
    emma = _recent_assistant_text(history_turns, n=6)
    if not emma or not _EMMA_PROMISED_DIRTY.search(emma):
        return False
    # She framed it filthy — any close / show / dirty follow-up keeps the band
    if _DIRECT_BUY.search(fan_message or "") or _COMPLY_AFTER_STALL.search(
        fan_message or ""
    ):
        return True
    if re.search(r"(?i)\b(guarr|dirty|explicit|picant|esa\s+foto|la\s+foto)\b", fan_message or ""):
        return True
    return False


def emma_owed_send(
    history_turns: Optional[List[Dict[str, str]]] = None,
) -> bool:
    """True if Emma just promised to send / asked him to beg for it."""
    emma = _recent_assistant_text(history_turns, n=4)
    return bool(emma and _EMMA_OWED_SEND.search(emma))


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
    """Seen media (free/purchased) + failed + currently open unpaid lock."""
    blocked = set(mem.get("sent_media_uuids") or []) | set(
        mem.get("failed_media_uuids") or []
    )
    # Open unpaid pitch: don't stack the same UUID again this episode
    if mem.get("last_ppv_pending") and mem.get("last_ppv_media_uuid"):
        blocked.add(str(mem["last_ppv_media_uuid"]))
    return blocked


def _recent_reject(mem: dict, *, minutes: int = 90) -> bool:
    raw = mem.get("last_reject_at")
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).total_seconds() < minutes * 60
    except (TypeError, ValueError):
        return False


def _zero_spender(mem: dict) -> bool:
    return int(mem.get("purchases") or 0) == 0 and float(
        mem.get("total_spent") or 0
    ) <= 0


def _price_bruised(mem: dict) -> bool:
    """
    True when a $0 fan already pushed back on price or was pitched high.

    Wider than the 90m reject window — complaining about $40 yesterday must
    still block another $40 today.
    """
    if _recent_reject(mem, minutes=60 * 24 * 7):
        return True
    last = max(
        float(mem.get("last_offer") or 0),
        float(mem.get("last_ppv_price") or 0),
    )
    # Pitched mid/high and never bought → next attach must come down a rung
    return _zero_spender(mem) and last >= 15.0


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
    history_turns: Optional[List[Dict[str, str]]] = None,
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
            _recent_assistant_text(history_turns, n=4),
        ]
    ).lower()
    rejected = _recent_reject(mem)
    bruised = _price_bruised(mem)
    # Emma-promise dirty is OK for buyers; $0 fans need HIM to ask hardcore.
    fan_explicit_dirty = wants_max_dirty(fan_message)
    max_dirty = (
        fan_explicit_dirty
        if _zero_spender(mem)
        else context_wants_max_dirty(fan_message, history_turns)
    )

    # Commercial band:
    #   $0 spenders → cheap L1–L2 first (convert), never open on $40
    #   Explicit hardcore ask THIS turn → L5–L7 exception
    #   After price pushback / high pitch that didn't convert → stay cheap
    if max_dirty:
        min_level, max_level = 5, 7
    elif _zero_spender(mem):
        # Cheap convert ladder — L1/L2 only until he spends
        min_level, max_level = 1, 2
    elif purchases < 2:
        min_level, max_level = 2, 5
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

    # Absolute ceiling for never-bought: no $40 / L6+ unless HE asked hardcore.
    if _zero_spender(mem) and not fan_explicit_dirty:
        cheap = [
            i
            for i in items
            if int(i.get("level") or 0) <= 3 and float(i.get("price") or 0) < 15
        ]
        if cheap:
            items = cheap
        # After a high pitch / reject: must undercut the last price
        if bruised and last_price > 0:
            under = [i for i in items if float(i.get("price") or 0) < last_price]
            if under:
                items = under

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

        # $0 / bruised: prefer CHEAP entry, not premium anchor
        if _zero_spender(mem) or (rejected and purchases == 0):
            target = 1 if (rejected or bruised or last_level == 0) else min(
                2, max(1, last_level)
            )
            value += 8 - abs(level - target) * 2.5
            if last_price and price < last_price:
                value += 4
            # Prefer lower price inside the band
            value += (15 - min(price, 15)) / 5
            value += float(item.get("score") or 0) / 10
            return value

        if purchases < 2:
            target = min(5, max(2, last_level + 1 if last_level else 3))
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
    mem: Optional[dict] = None,
    history_turns: Optional[List[Dict[str, str]]] = None,
    unpaid: bool = False,
) -> OfferChoice:
    direct = bool(_DIRECT_BUY.search(fan_message or "")) or bool(
        getattr(facts, "buying", False)
    )
    safe = not bool(getattr(facts, "heavy_vent", False))
    from core.sell_gate import should_attach_ppv

    attach_ok, _ = should_attach_ppv(
        mem or {},
        fan_message,
        facts=facts,
        history_turns=history_turns,
        unpaid=unpaid,
    )
    heat_close = attach_ok
    sell = bool(candidates) and (
        (direct and not _REJECT.search(fan_message or "") and safe)
        or (heat_close and safe)
    )
    return OfferChoice(
        sell_now=sell,
        offer=candidates[0] if sell else None,
        reason=reason if not heat_close else "heat-close attach",
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
    candidates = candidate_offers(
        mem, fan_message, history_turns=history_turns
    )
    if not candidates:
        return OfferChoice(False, None, "paid catalog exhausted", 1.0, "code")

    direct = bool(_DIRECT_BUY.search(fan_message or "")) or bool(
        getattr(facts, "buying", False)
    )
    max_dirty = context_wants_max_dirty(fan_message, history_turns)
    owed = emma_owed_send(history_turns)
    # She already said "pídemela / te la mando" — one comply closes. No 50 beg loop.
    if owed and _COMPLY_AFTER_STALL.search(fan_message or ""):
        direct = True
    if getattr(facts, "heavy_vent", False):
        return OfferChoice(False, None, "heavy vent: comfort first", 1.0, "code")
    from core.fan_pushback import is_fan_boundary

    if is_fan_boundary(fan_message or ""):
        return OfferChoice(False, None, "fan boundary: no sell", 1.0, "code")
    if mem.get("fan_boundary_active") or mem.get("photo_refusal_active") or mem.get("never_ask_fan_pic"):
        return OfferChoice(False, None, "fan boundary: no sell", 1.0, "code")
    if _REJECT.search(fan_message or "") and not direct:
        return OfferChoice(False, None, "current message rejects sale", 1.0, "code")
    if _CLARIFY_NO_SELL.search((fan_message or "").strip()):
        return OfferChoice(
            False,
            None,
            "clarify/cold check-in — not a PPV close",
            1.0,
            "code",
        )

    from core.sell_gate import chill_turn, should_attach_ppv

    if chill_turn(mem, fan_message, facts=facts, history_turns=history_turns):
        return OfferChoice(
            False,
            None,
            "heavy vent: comfort first",
            1.0,
            "code",
        )

    unpaid_now = bool(mem.get("last_ppv_pending")) or bool(
        getattr(facts, "ppv_unpaid", False) if facts is not None else False
    )
    attach_ok, attach_why = should_attach_ppv(
        mem,
        fan_message,
        facts=facts,
        history_turns=history_turns,
        unpaid=unpaid_now,
    )
    if attach_ok:
        return OfferChoice(
            True,
            candidates[0],
            f"sell_gate attach: {attach_why}",
            0.9,
            "code",
        )

    # $0 fans: no AI sell without ask/horny — rapport close only when warm enough
    if _zero_spender(mem) and not direct and not max_dirty:
        from core.turn_policy import _HORNY

        horny_now = bool(getattr(facts, "horny", False)) or bool(
            re.search(_HORNY, (fan_message or "").lower())
        )
        msgs_n = int(mem.get("messages") or 0)
        frees_n = int(mem.get("free_teases_sent") or 0)
        warm_signal = horny_now or bool(getattr(facts, "buying", False)) or bool(
            getattr(facts, "engacho", False)
        )
        # Deep heated chat ($0) — allow a cheap L1/L2 close without needing a free tease first
        deep_heat = msgs_n >= 6 and horny_now and (
            str(mem.get("status") or "") in ("warm", "spender", "whale")
            or msgs_n >= 10
        )
        # Free + depth + warm signal — avoids pushy sell on shy short chats
        rapport_close = msgs_n >= 12 and frees_n >= 1 and warm_signal
        if not horny_now and not rapport_close and not deep_heat:
            from core.chat_heat import _thread_horny

            if not _thread_horny(fan_message, history_turns, facts=facts):
                return OfferChoice(
                    False,
                    None,
                    "zero-spender needs clear ask/horny this turn",
                    1.0,
                    "code",
                )
    # Right after a lock vanished — reconnect first. No new PPV for ~10 min,
    # even on "enséñamela" (that was the extreme that felt spammy).
    # Only exception: he explicitly wants the dirtiest shot again.
    if _recently_expired(mem, minutes=10) and not max_dirty:
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
            mem=mem,
            history_turns=history_turns,
            unpaid=unpaid_now,
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
        "Sell ONLY on a natural close: he clearly asks for the photo / unlock, "
        "or several hot exchanges AND he is leaning in hard. "
        "If he EXPLICITLY asks for the dirtiest / 'más guarro' THIS message, "
        "pick the HIGHEST level candidate. "
        "If spent=0 / purchases=0: prefer the CHEAPEST L1/L2 candidate — "
        "never open on $40 / L6 unless wants_max_dirty=true on the current message. "
        "After recent_reject or a high last_offer that did not convert: stay cheap. "
        "Smalltalk, anger, spam complaints, price rejection, cold replies → do NOT sell. "
        "When in doubt, do NOT sell — reconnect beats a premature pitch. "
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
        f"emma_owed_send={owed}, "
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
            mem=mem,
            history_turns=history_turns,
            unpaid=unpaid_now,
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
            mem=mem,
            history_turns=history_turns,
            unpaid=unpaid_now,
        )
    # Code veto: AI must not cold-drop on clarify / zero-spender without ask
    if sell_now and _CLARIFY_NO_SELL.search((fan_message or "").strip()):
        sell_now = False
        chosen = None
        reason = f"clarify veto; selector said: {reason}"
    from core.turn_policy import _HORNY as _HORNY_SEL

    msgs_n = int(mem.get("messages") or 0)
    frees_n = int(mem.get("free_teases_sent") or 0)
    horny_msg = bool(getattr(facts, "horny", False)) or bool(
        re.search(_HORNY_SEL, (fan_message or "").lower())
    )
    warm_signal = horny_msg or bool(getattr(facts, "buying", False)) or bool(
        getattr(facts, "engacho", False)
    )
    rapport_close = msgs_n >= 12 and frees_n >= 1 and warm_signal
    deep_heat = msgs_n >= 10 and horny_msg
    if (
        sell_now
        and _zero_spender(mem)
        and not direct
        and not max_dirty
        and not horny_msg
        and not rapport_close
        and not deep_heat
    ):
        sell_now = False
        chosen = None
        reason = f"zero-spender veto (no clear ask); selector said: {reason}"

    if direct and not sell_now:
        chosen = candidates[0]
        sell_now = True
        reason = f"direct buy override; selector said: {reason}"
        confidence = max(confidence, 0.9)

    # Deep sexual RP + inventory → don't let the model soft-out of a cheap L1/L2
    if (
        not sell_now
        and candidates
        and _zero_spender(mem)
        and horny_msg
        and msgs_n >= 10
        and not _CLARIFY_NO_SELL.search((fan_message or "").strip())
    ):
        chosen = candidates[0]
        sell_now = True
        reason = f"deep-heat override ($0 + sexual RP); selector said: {reason}"
        confidence = max(confidence, 0.85)

    # She owed a send + he complied — never keep stalling
    if owed and direct and not sell_now:
        chosen = candidates[0]
        sell_now = True
        reason = f"owed-send override; selector said: {reason}"
        confidence = max(confidence, 0.95)

    # Max-dirty escalate: $0 fans only when HE asked hardcore this turn.
    # Emma promising "la más guarra" must not yank a never-buyer to $40.
    allow_dirty_escalate = max_dirty and (
        not _zero_spender(mem) or wants_max_dirty(fan_message)
    )
    if sell_now and allow_dirty_escalate and candidates:
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
        elif chosen is not None and int(chosen.get("level") or 0) < int(
            best.get("level") or 0
        ):
            chosen = best
            reason = f"max-dirty escalate → L{best.get('level')} {str(best.get('label') or '')[:40]}"
            confidence = max(confidence, 0.9)

    # Final belt: never-bought + no explicit hardcore → refuse $40 / L6+
    if (
        sell_now
        and chosen
        and _zero_spender(mem)
        and not wants_max_dirty(fan_message)
    ):
        lvl = int(chosen.get("level") or 0)
        price = float(chosen.get("price") or 0)
        if lvl >= 6 or price >= 40:
            cheap = [
                i
                for i in candidates
                if int(i.get("level") or 0) <= 3
                and float(i.get("price") or 0) < 15
            ]
            if cheap:
                chosen = min(
                    cheap,
                    key=lambda i: (
                        float(i.get("price") or 0),
                        int(i.get("level") or 0),
                    ),
                )
                reason = (
                    f"zero-spend ceiling → L{chosen.get('level')} "
                    f"${float(chosen.get('price') or 0):.0f}"
                )
                confidence = max(confidence, 0.9)
            else:
                return OfferChoice(
                    False,
                    None,
                    "zero-spend: no cheap candidate (refusing $40 open)",
                    1.0,
                    "code",
                )

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
