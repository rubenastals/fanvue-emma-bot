"""
SIMPLE-mode per-turn truth facts.

Live SIMPLE path injects only `truth_state()` — compact code-derived facts.
Tactics live in `personas/emma.md`. Do not reintroduce a fat STRATEGY essay
into every turn (that competed with persona + CRITICAL banners).

QUARANTINED — not the live SIMPLE brain: `STRATEGY_BLOCK` / `strategy_block()`
are offline/debug only (audit R3). Never re-inject the essay into live TURN.
"""
from __future__ import annotations

from typing import Optional


STRATEGY_BLOCK = """
HOW TO PLAY THIS CHAT (debug / offline only — not injected under SIMPLE live):

You are a real woman texting, not a sales bot. React to what he ACTUALLY just
said before anything else. Never paste the same line, question, or bit twice —
if you already used an angle in this chat, pick a different one.

Read his temperature every turn:
- HOT → escalate, tease, move toward a lock when STATUS attaches.
- WARM → build tension; one hook.
- COOL / HURT / VENTING → BACK OFF the sale. Reconnect. Zero dark techniques.

Hard truths (system enforces these too):
- Only mention a lock / price if LOCK STATUS or OFFER says one exists.
- PHOTOS only. Never promise video / clip / custom.
- Never claim you sent something unless a photo is attaching this turn.
- Never invent his name, a rival fan, an app glitch, or past gifts.

Voice: sweet + dirty, 1–2 short lines, emojis only if natural (often zero).
""".strip()


def truth_state(
    *,
    lock_active: Optional[bool] = None,
    offer_price: Optional[float] = None,
    cooling: bool = False,
    rival_used: bool = False,
    banned_openings: Optional[list] = None,
) -> str:
    """
    Compact, code-derived facts for THIS turn. Tactics live in the SIMPLE core;
    this only states what is TRUE right now so the model can't invent it.
    """
    bits = []
    if lock_active is True:
        bits.append("a REAL unpaid lock is waiting (its price is in LOCK STATUS)")
    elif lock_active is False:
        bits.append("NO lock is active — do NOT mention any candado/price/countdown")
    if offer_price and offer_price > 0:
        bits.append(
            f"a PAID photo (${offer_price:.0f}) attaches THIS turn — sell exactly that price"
        )
    if cooling:
        bits.append(
            "he is COOLING — de-escalate, reconnect, do NOT repeat a pitch, "
            "skip TECHNIQUE ENGINE this turn"
        )
    if rival_used:
        bits.append("the 'another fan is messaging me' bit was ALREADY used — banned now")
    if banned_openings:
        shown = ", ".join(f'"{o}"' for o in banned_openings[:5] if o)
        if shown:
            bits.append(
                f"BANNED openings this turn (you already used them): {shown}. "
                f"Start with a DIFFERENT first word — never Ay/Mmm/qué rico/pillín stamps."
            )
    if not bits:
        return ""
    return "TRUTH STATE THIS TURN:\n- " + "\n- ".join(bits)


def strategy_block(**kwargs) -> str:
    """Offline/debug helper — not used by SIMPLE live assemble."""
    ts = truth_state(**kwargs)
    return (STRATEGY_BLOCK + ("\n\n" + ts if ts else "")).strip()
