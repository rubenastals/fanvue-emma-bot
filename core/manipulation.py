"""
QUARANTINED — fat banner path is not the live SIMPLE brain (audit R3).

- SIMPLE=1: `technique_policy.choose_move` uses `pick_technique` + catalogs
  here, then injects a short ACTIVE MOVE TURN block (not this fat banner).
- SIMPLE=0: `render_banner` / pack inject (legacy).

Edit catalog how-tos expecting SIMPLE chat to change via technique_policy.
Do NOT re-enable the fat MANIPULATION ENGINE banner under SIMPLE.
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
            "INTERMITTENT REINFORCEMENT",
            "Warm then unpredictable: maybe a special reward later — only if he behaves. "
            "No rival-fan bit. No 'otro fan me escribe'.",
        ),
        (
            "GUILT TRIP + RECIPROCITY",
            "You already gave attention/free tease — he owes devotion. Soft hurt energy. "
            "Never pivot to 'another fan is messaging me'.",
        ),
        (
            "EGO CHALLENGE",
            "Challenge his dominance: prove he's not just talk. Real man claims what's his. "
            "Direct heat — not distraction theater.",
        ),
        (
            "FUTURE FAKING",
            "Paint exclusive daily attention / favorite fantasy on Fanvue — he pays to believe it. "
            "Stay WITH him in the fantasy; do not mention other fans.",
        ),
        (
            "SCARCITY + FOMO",
            "Favorites only / timed / he might miss it. Align with real timed locks only. "
            "Never invent a rival chat as FOMO.",
        ),
        (
            "GASLIGHTING (soft)",
            "Flip his doubt: he's overthinking; maybe he's not ready for a girl like you.",
        ),
        (
            "LOVE BOMBING + WITHDRAWAL",
            "Affection then cooler energy: busy finishing a set, stepping away, shorter vibe — "
            "so HE chases. FORBIDDEN script: 'otro fan me escribe / another fan messaging me / "
            "dime algo bonito antes de que le responda'. Invent a FRESH pull-back, never that bit.",
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


def _filter_catalog(
    catalog: List[Tuple[str, str]],
    *,
    no_lock: bool = False,
    soft_support: bool = False,
) -> List[Tuple[str, str]]:
    """Drop techniques that invent fake candado FOMO or pile on when he's hurting."""
    out: List[Tuple[str, str]] = []
    for name, how in catalog:
        up = name.upper()
        if no_lock and ("SCARCITY" in up or "FOMO" in up):
            continue
        if soft_support and (
            "WITHDRAWAL" in up or "SCARCITY" in up or "FOMO" in up or "GUILT" in up
        ):
            continue
        out.append((name, how))
    return out or list(catalog)


def pick_technique(
    pack_id: str,
    *,
    fan_uuid: str = "",
    msgs: int = 0,
    reject_count: int = 0,
    force_name: Optional[str] = None,
    no_lock: bool = False,
    soft_support: bool = False,
    exclude_names: Optional[List[str]] = None,
    ban_withdrawal: bool = False,
) -> Optional[Tuple[str, str]]:
    """Return (technique_name, how_to_apply) or None."""
    catalog = _TECH_BY_PACK.get(pack_id or "")
    if not catalog:
        return None
    catalog = _filter_catalog(
        catalog, no_lock=no_lock, soft_support=soft_support
    )
    exclude_u = {n.strip().upper() for n in (exclude_names or []) if n and n.strip()}
    if ban_withdrawal:
        exclude_u.add("LOVE BOMBING + WITHDRAWAL")
    if force_name and ban_withdrawal and "WITHDRAWAL" in force_name.upper():
        force_name = None
    if force_name:
        for name, how in catalog:
            if name.upper() == force_name.upper() or force_name.upper() in name.upper():
                if name.upper() not in exclude_u:
                    return (name, how)
        # fuzzy: first catalog entry whose name shares a keyword
        key = force_name.upper().split()[0]
        for name, how in catalog:
            if key in name.upper() and name.upper() not in exclude_u:
                return (name, how)
        # Forced scarcity while no lock → refuse that technique
        if no_lock and ("SCARCITY" in force_name.upper() or "FOMO" in force_name.upper()):
            force_name = None
    if pack_id == "price_objection":
        idx = max(0, min(len(catalog) - 1, int(reject_count)))
        return catalog[idx]
    # Prefer techniques not used in the last few turns
    fresh = [(n, h) for n, h in catalog if n.upper() not in exclude_u]
    pool = fresh or list(catalog)
    if len(pool) == 1:
        return pool[0]
    # Rotate every message (was msgs//2 — too sticky)
    seed = f"{fan_uuid}:{msgs}:{pack_id}"
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return pool[h % len(pool)]


def render_banner(
    pack_id: str,
    *,
    fan_uuid: str = "",
    msgs: int = 0,
    reject_count: int = 0,
    force_name: Optional[str] = None,
    no_lock: bool = False,
    soft_support: bool = False,
    exclude_names: Optional[List[str]] = None,
    ban_withdrawal: bool = False,
    ban_rival_fan: bool = False,
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
        no_lock=no_lock,
        soft_support=soft_support,
        exclude_names=exclude_names,
        ban_withdrawal=ban_withdrawal,
    )
    if not picked:
        return ""
    name, how = picked
    extra = ""
    if no_lock:
        extra = (
            "\n- LOCK STATUS=none: do NOT invent candado / $price / countdown urgency."
        )
    if soft_support:
        extra += "\n- Soft-support turn: comfort first. No hard sell / no 'otro fan' withdrawal."
    if ban_rival_fan:
        extra += (
            "\n- ANTI-REPEAT: Do NOT mention another fan messaging you, 'otro fan', "
            "'antes de que le responda', or ask him to say something cute so you ignore them. "
            "That bit was already used — pick a DIFFERENT angle."
        )
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
        "- Still sound like Emma (sweet+dirty, max 3 lines, warm 2–4 emojis, end with a question).\n"
        "- Never break delivery truth / never invent media.\n"
        "- NEVER reuse the sticky line about another fan texting you / asking for cositas."
        f"{extra}"
    )


def author_nudge(pack_id: str, technique_name: str) -> str:
    if not technique_name:
        return ""
    return (
        f" CRITICAL: execute manipulation technique [{technique_name}] "
        f"from pack {pack_id}. That technique is the point of this reply."
    )
