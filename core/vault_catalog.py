"""
Vault sell catalog — only real Fanvue media from our uploaded map.

Default source: exports/vault_rank_*/fanvue_media_map.json
Override with FANVUE_MEDIA_MAP=/path/to/fanvue_media_map.json

Ladder:
  L0 = free tease hooks (soft lingerie warm-up) — never paid, never repeat in-chat.
  L1+ = locked PPV. First paid pitch still anchors mid/high (not L0/L1 bait).
"""
from __future__ import annotations

import random
import re
from typing import Any, Dict, List, Optional

from db import vault_store

# First locked offer of a session aims here (then negotiate)
_ANCHOR_LEVELS = (4, 5, 3, 6)  # prefer open-nude / fingers, then soft nude, then hardcore


def load_items() -> List[Dict[str, Any]]:
    return vault_store.load_items()


def _already_sent(mem: dict) -> set:
    sent = set(mem.get("sent_media_uuids") or [])
    failed = set(mem.get("failed_media_uuids") or [])
    return sent | failed


def _paid_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """L1+ only — L0 is free-hook inventory, never locked."""
    return [i for i in items if int(i.get("level") or 0) >= 1]


def _l0_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [i for i in items if int(i.get("level") or 0) == 0]


def _pick_highest_price(pool: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Among pool, prefer higher price, then higher score (anchor high)."""
    if not pool:
        raise ValueError("empty pool")
    ranked = sorted(
        pool,
        key=lambda i: (float(i["price"]), int(i["score"]), int(i["level"])),
        reverse=True,
    )
    top = ranked[: min(3, len(ranked))]
    return random.choice(top)


def _pick_softest_l0(pool: List[Dict[str, Any]]) -> Dict[str, Any]:
    """L0 ladder: less explicit first (lower score, then filename)."""
    ranked = sorted(
        pool,
        key=lambda i: (int(i.get("score") or 0), str(i.get("file") or "")),
    )
    return ranked[0]


def select_free_tease(
    mem: dict,
    *,
    allow_repeat: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Next unused L0 photo for this fan (soft → hotter within L0).
    Never repeats a media_uuid already in sent_media_uuids.
    allow_repeat is ignored (kept for call-site compat) — same shot never twice.
    """
    del allow_repeat  # never re-send the same L0 to the same fan
    items = _l0_items(load_items())
    if not items:
        return None
    sent = _already_sent(mem)
    # Also treat previous-uuid aliases as already sent
    blocked = set(sent)
    for i in items:
        prev = i.get("media_uuid_previous")
        if prev and (i["media_uuid"] in sent or prev in sent):
            blocked.add(i["media_uuid"])
            blocked.add(prev)
    available = [i for i in items if i["media_uuid"] not in blocked and i.get("media_uuid_previous") not in blocked]
    if not available:
        return None
    return _pick_softest_l0(available)


def l0_count() -> int:
    return len(_l0_items(load_items()))


def l0_remaining(mem: dict) -> int:
    items = _l0_items(load_items())
    sent = _already_sent(mem)
    blocked = set(sent)
    for i in items:
        prev = i.get("media_uuid_previous")
        if prev and (i["media_uuid"] in sent or prev in sent):
            blocked.add(i["media_uuid"])
            blocked.add(prev)
    return sum(
        1
        for i in items
        if i["media_uuid"] not in blocked and i.get("media_uuid_previous") not in blocked
    )


def select_offer(
    mem: dict,
    fan_message: str = "",
    *,
    max_level: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Pick next PAID photo (L1+). Never picks L0. Never repeats media_uuid.
    """
    items = _paid_items(load_items())
    if not items:
        return None

    sent = _already_sent(mem)
    available = [i for i in items if i["media_uuid"] not in sent]
    if not available:
        # Exhausted paid catalog — do NOT silently re-send; caller skips.
        return None

    purchases = int(mem.get("purchases") or 0)
    spent = float(mem.get("total_spent") or 0)
    last_level = int(mem.get("last_offer_level") or 0)
    # Ignore L0 when reading last_level for paid ladder
    if last_level <= 0:
        last_level = 0
    offers_today = int(mem.get("offers_today") or 0)
    rejected_recently = bool(mem.get("last_reject_at"))

    low = (fan_message or "").lower()
    wants_more_explicit = bool(
        re.search(
            r"\b(m[aá]s|more|harder|dirt|guarra|expl[ií]cit|todo|naked|desnuda|"
            r"co[nñ]o|pussy|dildo|dedos)\b",
            low,
        )
    )

    if max_level is None:
        if purchases == 0 and spent <= 0 and offers_today == 0 and last_level == 0:
            max_level = 5
            min_level = 3
        elif rejected_recently and purchases == 0:
            min_level = 1
            max_level = max(1, last_level - 1) if last_level else 2
        elif purchases == 0 and spent <= 0:
            min_level = 3 if wants_more_explicit else 2
            max_level = 5 if wants_more_explicit else 4
            if last_level:
                min_level = max(min_level, min(4, last_level))
                max_level = max(max_level, min(5, last_level + 1))
        elif purchases < 2:
            min_level = max(3, last_level)
            max_level = min(6, max(4, last_level + 1))
        elif spent < 50:
            min_level = max(4, last_level)
            max_level = min(7, max(5, last_level + 1))
        else:
            min_level = max(5, last_level)
            max_level = 7
    else:
        min_level = 1

    pool = [
        i
        for i in available
        if min_level <= i["level"] <= max_level
    ]
    if not pool:
        pool = [i for i in available if i["level"] >= min_level]
    if not pool:
        pool = list(available)

    if purchases == 0 and offers_today == 0 and last_level == 0:
        for lvl in _ANCHOR_LEVELS:
            band = [i for i in pool if i["level"] == lvl]
            if band:
                return _pick_highest_price(band)

    if last_level and purchases > 0:
        climb = [i for i in pool if i["level"] >= last_level]
        if climb:
            return _pick_highest_price(climb)

    return _pick_highest_price(pool)


def free_tease_prompt_block(offer: Dict[str, Any]) -> str:
    return (
        "FREE TEASE PHOTO THIS TURN (unlocked gift — NOT pay-to-view):\n"
        f"- Shot vibe (INTERNAL ONLY — never paste this as chat text): {offer['label']}\n"
        "- Level: L0 warm-up tease\n"
        "- The SYSTEM will attach the real IMAGE with your FIRST chat bubble.\n"
        "RULES:\n"
        "- Write 1 short flirty line only (optional second tiny line). Warm tease — not a caption.\n"
        "- FORBIDDEN: narrating the photo shot-by-shot, pose/lingerie paragraphs, camera directions,\n"
          "  or pasting anything like a photo script/caption into the chat.\n"
        "- FORBIDDEN: writing '[envió una foto]', 'te envío una foto gratis', 'mira la foto:',\n"
          "  or describing what the image shows in detail. The app will SHOW the image itself.\n"
        "- Do NOT say it is locked / needs unlock. Do NOT claim it already arrived before attach.\n"
        "- Never invent videos or other shots."
    )


def offer_prompt_block(offer: Dict[str, Any]) -> str:
    if float(offer.get("price") or 0) <= 0 or int(offer.get("level") or 0) == 0:
        return free_tease_prompt_block(offer)
    price = offer["price"]
    return (
        "REAL CATALOG OFFER THIS TURN (you MUST sell ONLY this — nothing invented):\n"
        f"- Type: PHOTO (not a video)\n"
        f"- Shot vibe (INTERNAL ONLY — never paste as chat text): {offer['label']}\n"
        f"- Explicitness level: L{offer['level']} / score {offer.get('score', 0)}/10\n"
        f"- Price: ${price:.0f}\n"
        f"- Fanvue will lock the real IMAGE after your text (the system sends it).\n"
        "RULES:\n"
        "- Tease briefly then LOCK. Do NOT invent videos, customs, or other shots.\n"
        "- FORBIDDEN: asking permission ('quieres?', 'te la mando?', 'otra gratis?').\n"
        "- FORBIDDEN: offering free/gratis this turn — this is a PAID lock.\n"
        "- FORBIDDEN: asking HIM for his face/pic/selfie this turn — YOU are locking YOUR photo.\n"
        "- FORBIDDEN: dumping a pose/lingerie caption paragraph into chat.\n"
        "- Do NOT say you already sent it / check your inbox / I left it for you.\n"
        "- Say you're locking it now / about to lock it — then the system does.\n"
        "- Own the price confidently — premium, not a clearance sale.\n"
        "- Light scarcity OK: this lock won't sit forever (timed) — don't beg, don't countdown spam.\n"
        "- No fake 4K moaning videos we don't have."
    )


def sell_status_prompt_block(offer: Optional[Dict[str, Any]]) -> str:
    """
    Loud per-turn sell truth — same energy as LOCK STATUS.
    Code picks the catalog item BEFORE DeepSeek; she may only tease that item.
    """
    if offer and float(offer.get("price") or 0) > 0 and int(offer.get("level") or 0) > 0:
        price = float(offer["price"])
        label = (offer.get("label") or "vault photo")[:70]
        lvl = int(offer.get("level") or 0)
        return (
            "SELL STATUS = ATTACHING THIS TURN\n"
            f"- PHOTO L{lvl} ${price:.0f} — vibe (internal): {label}\n"
            "- The SYSTEM attaches this exact IMAGE with your first bubble.\n"
            "- Tease ONLY this photo. Mention the price at most once, naturally — don't lead with the number.\n"
            "- NEVER invent another shot, video, custom, clip, or second price."
        )
    if offer and (float(offer.get("price") or 0) <= 0 or int(offer.get("level") or 0) == 0):
        label = (offer.get("label") or "soft tease")[:70]
        return (
            "SELL STATUS = FREE L0 ATTACHING THIS TURN\n"
            f"- Soft PHOTO gift (internal vibe): {label}\n"
            "- System attaches the image. One short flirty line. Not a caption essay.\n"
            "- NEVER invent videos/customs or claim a paid lock this turn."
        )
    return (
        "SELL STATUS = NONE\n"
        "- No paid/free photo attaching this turn.\n"
        "- Flirt / heat / bond only.\n"
        "- ZERO prices, ZERO candados, ZERO videos/customs/clips, ZERO 'I'm sending it'."
    )


def catalog_summary_block(max_items: int = 12) -> str:
    items = load_items()
    if not items:
        return "CATALOG: empty — do NOT invent or claim you sent any locked content."
    by_lvl: Dict[int, int] = {}
    for i in items:
        by_lvl[i["level"]] = by_lvl.get(i["level"], 0) + 1
    lines = [
        "YOUR REAL VAULT (photos only — sell ONLY from this):",
        "L0 = soft FREE teases the SYSTEM attaches as real image files (warm-up gifts).",
        "You NEVER attach media by writing titles, brackets, or '[send him…]' / '[Transmite…]'.",
        "Only the system can attach. If no free gift is attached this turn, do not pretend.",
        "L1+ = locked PPV.",
        "SALES LADDER: first locked pitch = mid/high (L3–L5, pricey). "
        "Do NOT open paid pitches with the cheapest lingerie. Anchor high, then negotiate down if he resists.",
    ]
    for lvl in sorted(by_lvl):
        tag = " (FREE tease)" if lvl == 0 else ""
        lines.append(f"- L{lvl}{tag}: {by_lvl[lvl]} photos")
    paid = _paid_items(items)
    samples = sorted(paid, key=lambda i: i["price"], reverse=True)[:max_items]
    if samples:
        lines.append(
            "Pricier examples: "
            + "; ".join(f"L{i['level']} ${i['price']:.0f} {i['label']}" for i in samples[:8])
        )
    lines.append("Never invent videos or content not in this vault. Never re-send the same media_uuid in one chat.")
    return "\n".join(lines)
