"""
Emma reply engine — LIVE facade (audit R4).

Seams:
  core/reply_assemble.py  — prompt / history / TURN facts
  core/reply_sanitize.py  — post-draft belts / bubbles
  this module             — DeepSeek call + public re-exports

Production defaults (SIMPLE_PROMPT=1, LEAN_CREATIVE=1):
  CORE=personas/emma.md → CARD → HISTORY → TURN → AUTHOR → draft → sanitize
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI

from config import config
from core.prompt_core import EMMA_CORE_PROMPT  # noqa: F401 — kept for tests/legacy
from core.intent_router import RouteResult
from core.turn_policy import TurnDecision
from core.reply_assemble import (  # noqa: F401
    assemble_emma_turn,
    filter_messages_for_context,
    fan_message_display_text,
    fan_tip_or_gift_stub,
    fanvue_messages_to_turns,
    tip_amount_usd,
    _parse_msg_time,
    _looks_cooling,
    _ppv_truth_block,
    _usable_fan_name,
    _name_budget_note,
)
from core.reply_sanitize import (  # noqa: F401
    RewriteBudget,
    apply_post_draft,
    looks_incomplete_text,
    split_into_messages,
    _claims_unconfirmed_delivery,
    _enforce_delivery_truth,
    _fix_invented_wait_minutes,
    _strip_wrong_prices,
    _sanitize_reply,
    _trim_dangling_clause,
)
from core.reply_types import AssembledTurn  # noqa: F401

_CLIENT: Optional[OpenAI] = None

# Legacy constant (tests / old callers). Live path uses author_note_for(mode).
AUTHOR_NOTE = (
    "[Stay in character as Emma. Reply in 1-2 very short bubbles, usually one. "
    "Keep the full reply under ~220 characters, like real texting. "
    "Don't repeat your previous openings or emojis. React to his LAST message. "
    "If he's horny or asking for content, move toward locking PPV instead of stalling.]"
)


def _client() -> OpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
    return _CLIENT


def _call_creative(assembled: AssembledTurn, msgs: List[Dict[str, str]]) -> str:
    """One DeepSeek completion + first-pass _sanitize_reply."""
    kwargs = dict(
        model=config.DEEPSEEK_MODEL,
        messages=msgs,
        temperature=config.TEMPERATURE,
        top_p=config.TOP_P,
        frequency_penalty=config.FREQUENCY_PENALTY,
        presence_penalty=config.PRESENCE_PENALTY,
        max_tokens=config.MAX_RESPONSE_TOKENS,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
    resp = _client().chat.completions.create(**kwargs)
    offer = assembled.offer
    return _sanitize_reply(
        (resp.choices[0].message.content or "").strip(),
        want_spanish=assembled.want_spanish,
        fan_name=assembled.usable_name,
        name_confirmed=assembled.name_confirmed,
        name_max_uses=assembled.name_max_uses,
        media_attached=bool(offer),
        paid_lock=bool(
            offer
            and float(offer.get("price") or 0) > 0
            and int(offer.get("level") or 0) > 0
        ),
        ghost_free_ban=assembled.ghost_free_ban,
        voice_will_send=bool(assembled.voice_will_send),
    )


def generate_emma_reply(
    fan_message: str,
    *,
    history_turns: Optional[List[Dict[str, str]]] = None,
    fan_handle: str = "baby",
    fan_uuid: Optional[str] = None,
    decision: Optional[TurnDecision] = None,
    offer: Optional[dict] = None,
    want_spanish: Optional[bool] = None,
    ppv_status: Optional[dict] = None,
    fan_vision: Optional[dict] = None,
    delivery_truth: Optional[dict] = None,
    pack_id: Optional[str] = None,
    route_result: Optional[RouteResult] = None,
    voice_will_send: bool = False,
    turn_action: Optional[Any] = None,
    response_timing_plan: Optional[Any] = None,
    fan_message_age_minutes: Optional[float] = None,
) -> Tuple[str, TurnDecision]:
    """
    Assemble → creative draft → sanitize.

    Returns (raw_reply, decision). If `offer` is set, Emma must tease that photo only.
    """
    assembled = assemble_emma_turn(
        fan_message,
        history_turns=history_turns,
        fan_handle=fan_handle,
        fan_uuid=fan_uuid,
        decision=decision,
        offer=offer,
        want_spanish=want_spanish,
        ppv_status=ppv_status,
        fan_vision=fan_vision,
        delivery_truth=delivery_truth,
        pack_id=pack_id,
        route_result=route_result,
        voice_will_send=voice_will_send,
        turn_action=turn_action,
        response_timing_plan=response_timing_plan,
        fan_message_age_minutes=fan_message_age_minutes,
    )

    def _call(msgs: List[Dict[str, str]]) -> str:
        return _call_creative(assembled, msgs)

    reply = _call(assembled.messages)
    return apply_post_draft(reply, assembled, call=_call)
