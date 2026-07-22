"""
Live per-turn psychology move (SIMPLE path).

Protocol stays in code (ACTION / LOCK / SELL). Creativity is DeepSeek, but
each non-comfort turn gets ONE named move injected as a short TURN fact so
replies stop being generic flirt with no strategy.

Uses the catalogs in `manipulation.py` (picker only — not the fat banner).
"""
from __future__ import annotations

from typing import Any, List, Optional, Tuple

from core import manipulation


def effective_pack_for_move(
    pack_id: str,
    *,
    turn_action: Any = None,
    unpaid: bool = False,
    cooling: bool = False,
    soft_support: bool = False,
    soft_unpaid: bool = False,
) -> str:
    """
    Map this turn's situation → technique catalog pack.
    Empty string = skip psychology this turn.
    """
    if cooling or soft_support or soft_unpaid:
        return ""
    action = getattr(turn_action, "action", None) if turn_action is not None else None
    if action == "comfort":
        return ""
    if action == "send_voice":
        # Voice is the product — light love-bomb, not sell FOMO
        return "phase_hook"
    # Defend-price ladder beats generic unpaid scarcity
    if pack_id == "price_objection":
        return "price_objection"
    if unpaid or pack_id == "ppv_unpaid":
        return "ppv_unpaid"
    if action == "attach_ppv":
        if pack_id in ("phase_close", "lock_now", "escalate_paid"):
            return pack_id
        return "phase_close"
    if action == "attach_free":
        return "ask_free_first" if pack_id == "ask_free_first" else "phase_hook"
    # Plain flirt / pull / hook / spiral / reward / withdrawal
    if pack_id in manipulation._TECH_BY_PACK:
        return pack_id
    return "phase_pull"


def choose_move(
    pack_id: str,
    *,
    fan_uuid: str = "",
    msgs: int = 0,
    reject_count: int = 0,
    no_lock: bool = False,
    soft_support: bool = False,
    ban_withdrawal: bool = False,
    ban_rival_fan: bool = False,
    exclude_names: Optional[List[str]] = None,
    turn_action: Any = None,
    unpaid: bool = False,
    cooling: bool = False,
    soft_unpaid: bool = False,
) -> Optional[Tuple[str, str]]:
    """Return (name, how) or None when this turn should skip manip."""
    eff = effective_pack_for_move(
        pack_id or "",
        turn_action=turn_action,
        unpaid=unpaid,
        cooling=cooling,
        soft_support=soft_support,
        soft_unpaid=soft_unpaid,
    )
    if not eff:
        return None
    # Free tease catalog missing — fall back to hook love bomb
    if eff not in manipulation._TECH_BY_PACK:
        if eff == "ask_free_first":
            eff = "phase_hook"
        else:
            return None
    # Lock-price FOMO only when a real lock is in play (rival FOMO still OK)
    force_no_lock = bool(no_lock) and eff not in (
        "ppv_unpaid",
        "phase_close",
        "lock_now",
        "escalate_paid",
    )
    return manipulation.pick_technique(
        eff,
        fan_uuid=fan_uuid or "",
        msgs=msgs,
        reject_count=reject_count,
        no_lock=force_no_lock,
        soft_support=soft_support,
        exclude_names=exclude_names,
        ban_withdrawal=ban_withdrawal,
        ban_rival_fan=ban_rival_fan,
    )


def turn_block(name: str, how: str) -> str:
    """Compact TURN fact — not the legacy CRITICAL essay banner."""
    fam_id, principle = manipulation.family_for(name)
    fam_line = (
        f"- Family: {fam_id} {principle}\n" if fam_id else ""
    )
    return (
        "ACTIVE MOVE THIS TURN (mandatory — not optional flirt):\n"
        f"{fam_line}"
        f"- Move: {name}\n"
        f"- How: {how}\n"
        "- Your bubble MUST execute this angle. Never name the technique.\n"
        "- Vary the example beat — do not copy it verbatim.\n"
        "- Do NOT fall back to generic cute chat or a random soft check-in.\n"
        "- HARD BAN: IRL meetups, sextortion/leaks, invent trauma not in CLIENT CARD.\n"
        "- Rival jealousy + fake emergency moves ARE allowed when this move says so."
    )


def author_steer(name: str) -> str:
    if not name:
        return ""
    return (
        f" Execute ACTIVE MOVE [{name}] — that angle is the point of this bubble."
    )
