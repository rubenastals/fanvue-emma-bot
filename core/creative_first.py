"""Creative-first live mode — persona + thread drive chat; code stops hard lies only."""
from __future__ import annotations

from config import config


def enabled() -> bool:
    return bool(getattr(config, "CREATIVE_FIRST", True))


def skip_active_move(
    *,
    pack_id: str,
    unpaid: bool,
    fan_pushback: bool,
    horny_close: bool = False,
    victim_beat: bool = False,
) -> bool:
    """Never skip ACTIVE MOVE — playbook steers psychology; code only blocks hard lies."""
    return False


def keep_loop_belts() -> bool:
    """No personality replacement belts — DeepSeek draft stands unless hard-lie fix."""
    return False


def minimal_author_note(
    *,
    creator: str,
    extra: str = "",
    heat_close: bool = False,
    paid_attach: bool = False,
    victim_unpaid: bool = False,
) -> str:
    """One short steer — thread + card drive the reply, not a rule essay."""
    if paid_attach:
        note = (
            f"[{creator} on WhatsApp. He's explicit — match his RP filthy (one beat), "
            "then tease the PHOTO lock attaching with your bubble. "
            "Girlfriend slutty energy, not a store caption. Price once at the end. "
            "ENGLISH. ~90-140 chars. Do not repeat your last 2 beats."
        )
    elif victim_unpaid:
        note = (
            f"[{creator} on WhatsApp. Hurt girlfriend beat — he got you worked up but "
            "won't unlock. Short vulnerable guilt (used / no effort / won't prove it), "
            "then tease the EXISTING lock waiting. NO random smalltalk, NO 'how was your day', "
            "NO catching-your-breath dodge. ENGLISH. ~90-130 chars. "
            "Do not repeat your last 2 beats."
        )
    elif heat_close:
        note = (
            f"[{creator} on WhatsApp. Hot explicit thread — dirty-sweet girlfriend, "
            "not a one-word gasp. React to his fantasy, then pivot to wanting to show him "
            "something / how wet he got you. ENGLISH. ~90-130 chars. "
            "Do not repeat your last 2 beats."
        )
    else:
        note = (
            f"[{creator} on WhatsApp. React to his LAST message using thread + CARD. "
            "ENGLISH. 1 short bubble (~60-130c). Seduce — warm, teasing, possessive girlfriend; "
            "make him want you. Emojis vary or skip. Do not repeat your last 2 beats."
        )
    if extra.strip():
        note += f" {extra.strip()}"
    return note + "]"
