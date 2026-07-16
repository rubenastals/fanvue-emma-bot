"""
Vault sell catalog — only real Fanvue media from our uploaded map.

Default source: exports/vault_rank_*/fanvue_media_map.json
Override with FANVUE_MEDIA_MAP=/path/to/fanvue_media_map.json

Pricing ladder (anchor high):
  First pitch → mid/high explicitness + higher price (not lingerie bait).
  After reject → step down one rung.
  After buy → climb.
"""
from __future__ import annotations

import json
import os
import random
import re
from glob import glob
from pathlib import Path
from typing import Any, Dict, List, Optional

from db import vault_store

_ROOT = Path(__file__).resolve().parent.parent

# First locked offer of a session aims here (then negotiate)
_ANCHOR_LEVELS = (4, 5, 3, 6)  # prefer open-nude / fingers, then soft nude, then hardcore


def load_items() -> List[Dict[str, Any]]:
    return vault_store.load_items()


def _already_sent(mem: dict) -> set:
    sent = mem.get("sent_media_uuids") or []
    return set(sent)


def _pick_highest_price(pool: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Among pool, prefer higher price, then higher score (anchor high)."""
    if not pool:
        raise ValueError("empty pool")
    ranked = sorted(
        pool,
        key=lambda i: (float(i["price"]), int(i["score"]), int(i["level"])),
        reverse=True,
    )
    # small randomness among top 3 so it isn't identical every time
    top = ranked[: min(3, len(ranked))]
    return random.choice(top)


def select_offer(
    mem: dict,
    fan_message: str = "",
    *,
    max_level: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Pick next photo from OUR catalog only.

    Ladder: ANCHOR HIGH on the first pitch (L3–L5 / pricey), then climb after
    purchases or step down after rejects. Never repeat the same media_uuid.
    """
    items = load_items()
    if not items:
        return None

    sent = _already_sent(mem)
    available = [i for i in items if i["media_uuid"] not in sent]
    if not available:
        # catalog exhausted — reuse highest-priced unsent-by-level first
        available = sorted(items, key=lambda i: i["price"], reverse=True)

    purchases = int(mem.get("purchases") or 0)
    spent = float(mem.get("total_spent") or 0)
    last_level = int(mem.get("last_offer_level") or 0)
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

    # Target level band
    if max_level is None:
        if purchases == 0 and spent <= 0 and offers_today == 0 and last_level == 0:
            # FIRST pitch ever: aim mid-high (not L1 lingerie bait)
            max_level = 5
            min_level = 3
        elif rejected_recently and purchases == 0:
            # He pushed back — step down one rung from last, floor L2
            min_level = 2
            max_level = max(2, last_level - 1) if last_level else 3
        elif purchases == 0 and spent <= 0:
            # Still free — stay mid, can climb one if he asks dirtier
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
        # widen: anything at or above min_level
        pool = [i for i in available if i["level"] >= min_level]
    if not pool:
        pool = list(available)

    # First pitch: prefer anchor levels in order
    if purchases == 0 and offers_today == 0 and last_level == 0:
        for lvl in _ANCHOR_LEVELS:
            band = [i for i in pool if i["level"] == lvl]
            if band:
                return _pick_highest_price(band)

    # Prefer climbing above last offer when he is engaged
    if last_level and purchases > 0:
        climb = [i for i in pool if i["level"] >= last_level]
        if climb:
            return _pick_highest_price(climb)

    # Default: highest price in the allowed band (never bias to cheapest)
    return _pick_highest_price(pool)


def offer_prompt_block(offer: Dict[str, Any]) -> str:
    price = offer["price"]
    return (
        "REAL CATALOG OFFER THIS TURN (you MUST sell ONLY this — nothing invented):\n"
        f"- Type: PHOTO (not a video)\n"
        f"- Label: {offer['label']}\n"
        f"- Explicitness level: L{offer['level']} / score {offer['score']}/10\n"
        f"- Price: ${price:.0f}\n"
        f"- Fanvue will lock this photo in chat AFTER your text (the system sends it).\n"
        "RULES:\n"
        "- Tease THIS photo only. Do NOT invent videos, customs, or other shots.\n"
        "- Do NOT say you already sent it / check your inbox / I left it for you.\n"
        "- Say you're locking it / about to lock it for him now.\n"
        "- Price-anchor: own the price confidently — this is premium, not a clearance sale.\n"
        "- No fake 4K moaning videos we don't have."
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
        "SALES LADDER: first locked pitch = mid/high (L3–L5, pricey). "
        "Do NOT open with the cheapest lingerie. Anchor high, then negotiate down if he resists.",
    ]
    for lvl in sorted(by_lvl):
        lines.append(f"- L{lvl}: {by_lvl[lvl]} photos")
    samples = sorted(items, key=lambda i: i["price"], reverse=True)[:max_items]
    lines.append(
        "Pricier examples: "
        + "; ".join(f"L{i['level']} ${i['price']:.0f} {i['label']}" for i in samples[:8])
    )
    lines.append("Never invent videos or content not in this vault.")
    return "\n".join(lines)
