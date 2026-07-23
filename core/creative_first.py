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
) -> bool:
    """No psychology ACTIVE MOVE unless sell or pushback needs it."""
    if not enabled():
        return False
    if fan_pushback:
        return False
    if unpaid or pack_id in (
        "ppv_unpaid",
        "phase_close",
        "lock_now",
        "escalate_paid",
        "price_objection",
    ):
        return False
    return True


def keep_loop_belts() -> bool:
    """Deterministic anti-loop belts (love-bomb, duplicate) — safe in creative-first."""
    return enabled()


def minimal_author_note(*, creator: str, extra: str = "") -> str:
    """One short steer — thread + card drive the reply, not a rule essay."""
    note = (
        f"[{creator} on WhatsApp. React to his LAST message using recent thread + "
        "CLIENT CARD. ENGLISH. 1 short bubble (~60-90c). Girlfriend vibe, not sales "
        "script. Do not repeat your last 2 beats."
    )
    if extra.strip():
        note += f" {extra.strip()}"
    return note + "]"
