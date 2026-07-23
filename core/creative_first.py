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
