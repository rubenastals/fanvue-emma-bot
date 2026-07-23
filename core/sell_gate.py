"""
Single sell policy — when to attach PPV or nudge an unpaid lock.

Never hard-block sales for hours because of bills / broke signals.
Chill = this turn only (soft decline, sell streak). Hot = always press.
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
from core.soft_decline import is_broke_soft, is_soft_decline


@dataclass
class SellGateResult:
    attach: bool
    nudge_unpaid: bool
    chill: bool
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
    Aflojar ESTE turno — no attach, no unlock nag. Not a multi-hour block.
    """
    if getattr(facts, "heavy_vent", False):
        return True
    msg = (fan_message or "").strip()
    if is_soft_decline(msg) or is_broke_soft(msg):
        # Bills / not now — bond this beat; next horny turn can sell again.
        if not explicit_horny_now(msg) and not _thread_horny(
            msg, history_turns, facts=facts
        ):
            return True
    streak = _sell_lock_streak(mem or {})
    if streak >= 2 and not _thread_horny(msg, history_turns, facts=facts):
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
                reason="hot-unpaid-nudge",
            )
        if chill:
            return SellGateResult(
                attach=False,
                nudge_unpaid=False,
                chill=True,
                reason="chill-turn-unpaid",
            )
        return SellGateResult(
            attach=False,
            nudge_unpaid=False,
            chill=False,
            reason="unpaid-cold",
        )

    if chill:
        return SellGateResult(
            attach=False,
            nudge_unpaid=False,
            chill=True,
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
                reason=f"hot-thread score={score}",
            )

    return SellGateResult(
        attach=False,
        nudge_unpaid=False,
        chill=False,
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
