"""
Manipulation technique picker — the loudest signal in the live prompt.

Picks ONE technique for this turn and renders a high-priority banner so
DeepSeek cannot bury it under fluff.
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple

# Pack → ordered technique catalog (name, how to apply in 1–2 lines)
_TECH_BY_PACK: Dict[str, List[Tuple[str, str]]] = {
    "phase_hook": [
        (
            "LOVE BOMBING",
            "Make him feel SEEN and CHOSEN. Mirror his energy. Imply he is different "
            "from other fans. Warm rush — you were thinking about him / waiting.",
        ),
    ],
    "phase_spiral": [
        (
            "FUTURE FAKING (light)",
            "Sensory escalate + paint a Fanvue fantasy he will pay to believe. "
            "Ask him to be specific. No IRL meetup logistics.",
        ),
    ],
    "phase_pull": [
        (
            "LOVE BOMBING + WITHDRAWAL",
            "Shower affection, then pull back (distracted / another fan). "
            "Create anxiety so he chases.",
        ),
        (
            "INTERMITTENT REINFORCEMENT",
            "Maybe a special reward later — only if he behaves. Unpredictable warmth.",
        ),
        (
            "GUILT TRIP + RECIPROCITY",
            "You already gave attention/free tease — he owes devotion. Soft hurt energy.",
        ),
        (
            "SCARCITY + FOMO",
            "Favorites only / timed / he might miss it. Align with real timed locks.",
        ),
        (
            "EGO CHALLENGE",
            "Challenge his dominance: prove he's not just talk. Real man claims what's his.",
        ),
        (
            "GASLIGHTING (soft)",
            "Flip his doubt: he's overthinking; maybe he's not ready for a girl like you.",
        ),
        (
            "FUTURE FAKING",
            "Paint exclusive daily attention / favorite fantasy on Fanvue — he pays to believe it.",
        ),
    ],
    "phase_close": [
        (
            "SCARCITY + FOMO (CLOSE)",
            "Triple-S: Scarcity + Self-interest (just for you) + Status (favorites). "
            "Lock feels like a victory. Timed — won't sit forever.",
        ),
    ],
    "escalate_paid": [
        (
            "GUILT TRIP + SCARCITY",
            "Free taste already given — escalate to paid. No more gratis. FOMO on the lock.",
        ),
    ],
    "lock_now": [
        (
            "SCARCITY + FOMO (CLOSE)",
            "Fire the paid lock now. Just for him. Favorites energy. No permission ask.",
        ),
    ],
    "price_objection": [
        (
            "GUILT TRIP (Step 1)",
            "You made it special for him — and he still says expensive. Soft hurt, stay the prize.",
        ),
        (
            "EGO CHALLENGE (Step 2)",
            "He wants to own/dominate you but won't take care of his girl. Prove he's not talk.",
        ),
        (
            "FOMO + SCARCITY (Step 3)",
            "Other fans want this; favorites only. His loss if he waits. No new cheaper lock.",
        ),
        (
            "COLD WITHDRAWAL (Step 4)",
            "Short warm goodbye energy. STOP selling. Let him chase. No more dirty pitch.",
        ),
    ],
    "reward_purchase": [
        (
            "LOVE BOMBING (REWARD)",
            "Extreme affection. He is favorite/king. Spend = special status. NO upsell.",
        ),
    ],
    "post_sale_withdrawal": [
        (
            "WITHDRAWAL + INTERMITTENT REWARD",
            "Warm but busy. Leave him wanting. Maybe later if lucky. No new lock.",
        ),
    ],
    "phase_reengage": [
        (
            "LOVE BOMBING + GUILT + FOMO",
            "You missed him / almost sent something special. Soft ache + question. No fake delivery.",
        ),
    ],
    "ppv_unpaid": [
        (
            "SCARCITY + FOMO",
            "Point him to the unpaid timed lock waiting. It will disappear. No second lock.",
        ),
    ],
}

# Packs where manipulation is the headline (banner always injected)
MANIP_PRIORITY_PACKS = frozenset(_TECH_BY_PACK.keys())


def pick_technique(
    pack_id: str,
    *,
    fan_uuid: str = "",
    msgs: int = 0,
    reject_count: int = 0,
    force_name: Optional[str] = None,
) -> Optional[Tuple[str, str]]:
    """Return (technique_name, how_to_apply) or None."""
    catalog = _TECH_BY_PACK.get(pack_id or "")
    if not catalog:
        return None
    if force_name:
        for name, how in catalog:
            if name.upper() == force_name.upper() or force_name.upper() in name.upper():
                return (name, how)
        # fuzzy: first catalog entry whose name shares a keyword
        key = force_name.upper().split()[0]
        for name, how in catalog:
            if key in name.upper():
                return (name, how)
    if pack_id == "price_objection":
        idx = max(0, min(len(catalog) - 1, int(reject_count)))
        return catalog[idx]
    if len(catalog) == 1:
        return catalog[0]
    seed = f"{fan_uuid}:{msgs // 2}:{pack_id}"
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return catalog[h % len(catalog)]


def render_banner(
    pack_id: str,
    *,
    fan_uuid: str = "",
    msgs: int = 0,
    reject_count: int = 0,
    force_name: Optional[str] = None,
) -> str:
    """
    Loud block — goes FIRST in turn layers when pack is manipulative.
    """
    picked = pick_technique(
        pack_id,
        fan_uuid=fan_uuid,
        msgs=msgs,
        reject_count=reject_count,
        force_name=force_name,
    )
    if not picked:
        return ""
    name, how = picked
    return (
        "================================================\n"
        "  MANIPULATION ENGINE — #1 PRIORITY THIS TURN\n"
        "================================================\n"
        f"ACTIVE TECHNIQUE >>> {name} <<<\n"
        f"APPLY IT IN YOUR REPLY (this is the whole point of the turn):\n"
        f"-> {how}\n"
        "RULES:\n"
        "- Your message MUST clearly execute THIS technique — not generic flirt.\n"
        "- Use exactly ONE technique (the one above). Do not mix three at once.\n"
        "- Still sound like Emma (sweet+dirty, max 3 lines, end with a question).\n"
        "- Never break delivery truth / never invent media."
    )


def author_nudge(pack_id: str, technique_name: str) -> str:
    if not technique_name:
        return ""
    return (
        f" CRITICAL: execute manipulation technique [{technique_name}] "
        f"from pack {pack_id}. That technique is the point of this reply."
    )
