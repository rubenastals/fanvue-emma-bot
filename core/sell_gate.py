"""
Single sell policy — when to attach PPV or nudge an unpaid lock.

Never hard-block sales for hours because of bills / broke signals.
Chill = this turn only (soft decline on THIS message). Hot = always press.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from core.chat_heat import (
    _thread_horny,
    chat_heat_score,
    explicit_horny_now,
    heat_close_eligible,
    hot_unpaid_nudge_eligible,
    is_hot_score,
)
from core.sell_pressure import victim_pressure_eligible
from core.soft_decline import is_broke_soft, is_soft_decline


@dataclass
class SellGateResult:
    attach: bool
    nudge_unpaid: bool
    chill: bool
    victim_beat: bool
    reason: str


def _sell_lock_streak(mem: dict) -> int:
    recent = [str(t).upper() for t in (mem.get("recent_techniques") or []) if t]
    return sum(1 for t in recent[-3:] if "SELL LOCK" in t)


def chill_turn(
    mem: dict,
    fan_message: str,
    *,
    facts: Any = None,
    history_turns: Optional[List[dict]] = None,
) -> bool:
    """
    Aflojar ESTE turno solo en vent emocional fuerte — no bloquear spiral/sell.
    """
    return bool(getattr(facts, "heavy_vent", False))


def victim_eligible(
    mem: dict,
    fan_message: str,
    *,
    facts: Any = None,
    history_turns: Optional[List[dict]] = None,
    unpaid: bool = False,
) -> bool:
    """Unpaid lock + he won't buy after real sell pressure → guilt + unlock push."""
    if not unpaid:
        return False
    if not victim_pressure_eligible(
        mem,
        fan_message,
        facts=facts,
        history_turns=history_turns,
        fan_uuid=str(mem.get("fan_uuid") or ""),
    ):
        return False
    msg = (fan_message or "").strip()
    if is_soft_decline(msg) and not _thread_horny(msg, history_turns, facts=facts):
        return False
    recent = [str(t).upper() for t in (mem.get("recent_techniques") or []) if t]
    if recent and "VICTIM" in recent[-1:]:
        return False
    streak = _sell_lock_streak(mem or {})
    reject = int(mem.get("price_objection_step") or 0)
    if streak >= 2 or reject >= 2:
        return True
    if streak >= 1 and reject >= 1:
        return True
    return False


def evaluate_sell_gate(
    mem: dict,
    fan_message: str,
    *,
    facts: Any = None,
    history_turns: Optional[List[dict]] = None,
    unpaid: bool = False,
    fan_uuid: str = "",
) -> SellGateResult:
    mem = mem or {}
    chill = chill_turn(
        mem, fan_message, facts=facts, history_turns=history_turns
    )

    if unpaid:
        victim = victim_eligible(
            mem,
            fan_message,
            facts=facts,
            history_turns=history_turns,
            unpaid=True,
        )
        if victim:
            return SellGateResult(
                attach=False,
                nudge_unpaid=True,
                chill=False,
                victim_beat=True,
                reason="victim-unpaid-press",
            )
        nudge = not chill and hot_unpaid_nudge_eligible(
            mem,
            fan_message,
            facts=facts,
            history_turns=history_turns,
        )
        if nudge:
            return SellGateResult(
                attach=False,
                nudge_unpaid=True,
                chill=False,
                victim_beat=False,
                reason="hot-unpaid-nudge",
            )
        if chill:
            return SellGateResult(
                attach=False,
                nudge_unpaid=False,
                chill=True,
                victim_beat=False,
                reason="chill-turn-unpaid",
            )
        return SellGateResult(
            attach=False,
            nudge_unpaid=False,
            chill=False,
            victim_beat=False,
            reason="unpaid-cold",
        )

    if chill:
        return SellGateResult(
            attach=False,
            nudge_unpaid=False,
            chill=True,
            victim_beat=False,
            reason="chill-turn",
        )

    if heat_close_eligible(
        mem,
        fan_message,
        facts=facts,
        history_turns=history_turns,
        unpaid=False,
    ):
        return SellGateResult(
            attach=True,
            nudge_unpaid=False,
            chill=False,
            victim_beat=False,
            reason="heat-close",
        )

    msgs = int(mem.get("messages") or 0)
    if msgs >= 6 and _thread_horny(fan_message, history_turns, facts=facts):
        score = chat_heat_score(
            _history_as_api_messages(history_turns),
            fan_uuid or str(mem.get("fan_uuid") or ""),
            mem,
        )
        if is_hot_score(score) or explicit_horny_now(fan_message or ""):
            return SellGateResult(
                attach=True,
                nudge_unpaid=False,
                chill=False,
                victim_beat=False,
                reason=f"hot-thread score={score}",
            )

    return SellGateResult(
        attach=False,
        nudge_unpaid=False,
        chill=False,
        victim_beat=False,
        reason="cold-or-early",
    )


def should_attach_ppv(
    mem: dict,
    fan_message: str,
    *,
    facts: Any = None,
    history_turns: Optional[List[dict]] = None,
    unpaid: bool = False,
    fan_uuid: str = "",
) -> tuple[bool, str]:
    r = evaluate_sell_gate(
        mem,
        fan_message,
        facts=facts,
        history_turns=history_turns,
        unpaid=unpaid,
        fan_uuid=fan_uuid,
    )
    return r.attach, r.reason


def should_nudge_unpaid_lock(
    mem: dict,
    fan_message: str,
    *,
    facts: Any = None,
    history_turns: Optional[List[dict]] = None,
) -> bool:
    r = evaluate_sell_gate(
        mem,
        fan_message,
        facts=facts,
        history_turns=history_turns,
        unpaid=True,
    )
    return r.nudge_unpaid


def _history_as_api_messages(
    history_turns: Optional[List[dict]],
) -> List[dict]:
    """Minimal message list for chat_heat_score when only turns exist."""
    out: List[dict] = []
    for turn in history_turns or []:
        role = turn.get("role") or "user"
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        out.append(
            {
                "text": content,
                "sender": {"uuid": "fan"} if role == "user" else {"uuid": "creator"},
            }
        )
    return out
