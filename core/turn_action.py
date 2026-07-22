"""
Action-first turn planner (audit R5).

Code decides WHAT happens this turn before DeepSeek writes text:
  send_voice > comfort > attach_ppv > attach_free > flirt

DeepSeek only writes words for the chosen ACTION — it does not own protocol.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.turn_policy import MODE_CHILL, _HEAVY_VENT

ACTION_FLIRT = "flirt"
ACTION_SEND_VOICE = "send_voice"
ACTION_ATTACH_PPV = "attach_ppv"
ACTION_ATTACH_FREE = "attach_free"
ACTION_COMFORT = "comfort"

_ALL_ACTIONS = frozenset(
    {
        ACTION_FLIRT,
        ACTION_SEND_VOICE,
        ACTION_ATTACH_PPV,
        ACTION_ATTACH_FREE,
        ACTION_COMFORT,
    }
)


@dataclass
class TurnAction:
    action: str
    reason: str
    voice: bool = False
    blocks_photo: bool = False
    offer: Optional[Dict[str, Any]] = None
    mem: Optional[Dict[str, Any]] = None
    # Optional pack hint when unpaid / demote changed creative rails
    pack_id: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.action not in _ALL_ACTIONS:
            raise ValueError(f"unknown TurnAction.action={self.action!r}")
        if self.action == ACTION_SEND_VOICE:
            self.voice = True
            self.blocks_photo = True
            self.offer = None

    @property
    def voice_will_send(self) -> bool:
        return bool(self.voice) and self.action == ACTION_SEND_VOICE

    @property
    def attaches_photo(self) -> bool:
        return self.action in (ACTION_ATTACH_PPV, ACTION_ATTACH_FREE) and bool(
            self.offer
        )


def wants_comfort(
    fan_message: str,
    *,
    decision: Any = None,
    pack_id: str = "",
    facts: Any = None,
) -> bool:
    """True when this turn must comfort / reconnect — no sell, no tease-lock."""
    if facts is not None and bool(getattr(facts, "heavy_vent", False)):
        return True
    mode = (getattr(decision, "mode", None) or "") if decision is not None else ""
    if mode == MODE_CHILL:
        return True
    # Soft broke / billing pushback packs still sell-script elsewhere; only
    # heavy emotional vent forces comfort ACTION.
    if re.search(_HEAVY_VENT, fan_message or "", re.I):
        return True
    return False


def classify_turn_action(
    *,
    voice_ok: bool,
    voice_why: str = "",
    blocks_photo: bool = False,
    unpaid: bool = False,
    offer: Optional[Dict[str, Any]] = None,
    comfort: bool = False,
    mem: Optional[Dict[str, Any]] = None,
    pack_id: str = "",
) -> TurnAction:
    """
    Pure priority ladder (no I/O). Used by plan_turn_action + tests.

    Priority: send_voice > comfort > attach_ppv > attach_free > flirt
    """
    if voice_ok:
        return TurnAction(
            action=ACTION_SEND_VOICE,
            reason=voice_why or "open_voice",
            voice=True,
            blocks_photo=True,
            offer=None,
            mem=mem,
            pack_id=pack_id,
        )

    if comfort:
        return TurnAction(
            action=ACTION_COMFORT,
            reason="comfort — heavy vent / chill (no sell)",
            blocks_photo=True,  # no photo while comforting
            offer=None,
            mem=mem,
            pack_id=pack_id,
        )

    if unpaid:
        return TurnAction(
            action=ACTION_FLIRT,
            reason="unpaid lock open — push unlock, no new attach",
            blocks_photo=bool(blocks_photo),
            offer=None,
            mem=mem,
            pack_id=pack_id or "ppv_unpaid",
        )

    if blocks_photo:
        return TurnAction(
            action=ACTION_FLIRT,
            reason=f"voice protocol blocks photo ({voice_why or 'debt'})",
            blocks_photo=True,
            offer=None,
            mem=mem,
            pack_id=pack_id,
        )

    if offer:
        price = float(offer.get("price") or 0)
        level = int(offer.get("level") or 0)
        if price > 0 and level > 0:
            return TurnAction(
                action=ACTION_ATTACH_PPV,
                reason=f"paid lock ${price:.0f}",
                offer=offer,
                mem=mem,
                pack_id=pack_id,
            )
        return TurnAction(
            action=ACTION_ATTACH_FREE,
            reason="free tease L0",
            offer=offer,
            mem=mem,
            pack_id=pack_id,
        )

    return TurnAction(
        action=ACTION_FLIRT,
        reason="flirt / reconnect (no attach)",
        mem=mem,
        pack_id=pack_id,
    )


def plan_turn_action(
    *,
    fan_uuid: str,
    fan_handle: str,
    fan_message: str,
    mem: dict,
    decision: Any,
    pack_id: str,
    unpaid: bool,
    history_turns: Optional[List[Dict[str, Any]]],
    want_sell: bool,
    want_free: bool,
    facts: Any = None,
) -> TurnAction:
    """
    One resolver before the LLM: voice FSM → comfort → offer select → classify.

    Offer selection uses the same vault / offer_selector as the poller.
    """
    from core import offer_selector, vault_catalog, voice_notes as vn

    voice_ok, voice_why, mem2, blocks_photo = vn.resolve_voice_action(
        fan_uuid=fan_uuid,
        fan_handle=fan_handle,
        fan_message=fan_message,
        mem=mem,
        decision=decision,
        pack_id=pack_id,
        unpaid=unpaid,
        history_turns=history_turns,
    )

    comfort = wants_comfort(
        fan_message, decision=decision, pack_id=pack_id, facts=facts
    )

    # Voice send / photo-block / comfort / unpaid → never pick a new offer
    offer: Optional[Dict[str, Any]] = None
    demote_reason = ""
    if (
        not voice_ok
        and not blocks_photo
        and not comfort
        and not unpaid
    ):
        if want_free:
            offer = vault_catalog.select_free_tease(mem2)
        elif want_sell:
            selection = offer_selector.choose_offer(
                mem2,
                fan_message,
                history_turns=history_turns,
                facts=facts,
            )
            if selection.sell_now:
                offer = selection.offer
            else:
                demote_reason = (selection.reason or "")[:120]
                pack_id = "phase_pull"

    ta = classify_turn_action(
        voice_ok=voice_ok,
        voice_why=voice_why,
        blocks_photo=blocks_photo,
        unpaid=unpaid,
        offer=offer,
        comfort=comfort,
        mem=mem2,
        pack_id=pack_id,
    )
    if demote_reason:
        ta.extras["demote_reason"] = demote_reason
    if voice_ok or blocks_photo:
        ta.extras["voice_why"] = voice_why
    return ta


def commitment_prompt_line(mem: Optional[dict], *, voice_will_send: bool) -> str:
    """
    One code-truth line for the prompt. Not an essay — protocol lives in code.
    """
    mem = mem or {}
    c = mem.get("open_commitment")
    if not isinstance(c, dict):
        c = None
    ctype = (c or {}).get("type") or ""
    if voice_will_send or ctype == "voice":
        hits = int((c or {}).get("hits") or 0)
        hit_bit = f" (asked/teased x{hits})" if hits else ""
        return (
            "COMMITMENT (code — law this turn):\n"
            f"- type=voice{hit_bit}. System WILL send a voice note after your text "
            "if ACTION=send_voice. HARD BAN: pídemelo / ask me nicely / "
            "'quieres un audio?'. Do not re-open the beg loop."
        )
    return ""


def action_prompt_line(ta: Optional[TurnAction], *, mem: Optional[dict] = None) -> str:
    """Compact ACTION truth for TURN — DeepSeek writes text for this only."""
    if ta is None:
        return ""
    mem = mem if mem is not None else ta.mem
    if ta.action == ACTION_SEND_VOICE:
        return commitment_prompt_line(mem, voice_will_send=True)
    if ta.action == ACTION_COMFORT:
        return (
            "ACTION (code — law this turn):\n"
            "- comfort / reconnect only. No price, no candado tease, no free gift pitch."
        )
    if ta.action == ACTION_ATTACH_PPV and ta.offer:
        price = float(ta.offer.get("price") or 0)
        return (
            "ACTION (code — law this turn):\n"
            f"- attach_ppv ${price:.0f}. Filthy girlfriend tease of THIS paid lock "
            f"(body want → unlock). No store caption. Do not ask for his pic."
        )
    if ta.action == ACTION_ATTACH_FREE and ta.offer:
        return (
            "ACTION (code — law this turn):\n"
            "- attach_free L0. Warm gift — no price talk."
        )
    if ta.blocks_photo:
        return (
            "ACTION (code — law this turn):\n"
            "- flirt only. Photo/PPV HARD-BLOCKED (voice protocol). No lock talk as if sending."
        )
    return ""
