"""
When aggressive unpaid sell (VICTIM / hard SELL LOCK) is *earned*.

Unpaid alone is not enough — early/cold fans with one stray lock must not get
guilt or hard press. Hot thread + rapport depth must be proven first.
"""
from __future__ import annotations

from typing import Any, List, Optional

from core.chat_heat import (
    _thread_horny,
    chat_heat_score,
    is_hot_score,
    is_warm_score,
)

# Match playbook early-romance window (~first 12 msgs)
_EARNED_MIN_MSGS = 12

_HEAT_TECHNIQUES = frozenset({"HEAT", "SELL LOCK", "VICTIM", "HOLD FRAME"})


def _recent_heat_in_techniques(mem: dict, *, lookback: int = 6) -> bool:
    recent = [str(t).upper() for t in (mem.get("recent_techniques") or []) if t]
    for t in recent[-lookback:]:
        if t in _HEAT_TECHNIQUES:
            return True
    return False


def _recent_heat_in_list(recent_techs: list, *, lookback: int = 6) -> bool:
    for t in [str(x).upper() for x in recent_techs if x][-lookback:]:
        if t in _HEAT_TECHNIQUES:
            return True
    return False


def earned_from_signals(sig: dict, recent_techs: list | None = None) -> bool:
    """Playbook path — sig + recent technique names."""
    msgs = int(sig.get("msgs") or 0)
    if msgs < _EARNED_MIN_MSGS:
        return False
    if sig.get("horny") or sig.get("flirting"):
        return True
    if sig.get("earned_pressure"):
        return True
    if recent_techs and _recent_heat_in_list(recent_techs):
        return True
    return False


def earned_sell_pressure(
    mem: dict,
    fan_message: str,
    *,
    facts: Any = None,
    history_turns: Optional[List[dict]] = None,
    messages: Optional[list] = None,
    fan_uuid: str = "",
    min_msgs: int = _EARNED_MIN_MSGS,
) -> bool:
    """
    True when guilt / hard unpaid press is allowed this thread.

    Requires rapport depth AND proven heat (not just an unpaid flag in memory).
    """
    mem = mem or {}
    msgs = int(mem.get("messages") or 0)
    if msgs < min_msgs:
        return False

    if _thread_horny(fan_message or "", history_turns, facts=facts):
        return True

    if _recent_heat_in_techniques(mem):
        return True

    if messages:
        score = chat_heat_score(messages, fan_uuid or "", mem)
        if is_warm_score(score):
            return True

    return False


def victim_pressure_eligible(
    mem: dict,
    fan_message: str,
    *,
    facts: Any = None,
    history_turns: Optional[List[dict]] = None,
    messages: Optional[list] = None,
    fan_uuid: str = "",
) -> bool:
    """VICTIM guilt — stricter than general sell pressure (must be clearly hot)."""
    mem = mem or {}
    if not earned_sell_pressure(
        mem,
        fan_message,
        facts=facts,
        history_turns=history_turns,
        messages=messages,
        fan_uuid=fan_uuid,
    ):
        return False
    if _thread_horny(fan_message or "", history_turns, facts=facts):
        return True
    if _recent_heat_in_techniques(mem, lookback=4):
        return True
    if messages and is_hot_score(
        chat_heat_score(messages, fan_uuid or "", mem)
    ):
        return True
    return False
