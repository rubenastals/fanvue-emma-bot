"""
Temporary LLM supervisor — humanity gate before send.

Judges whether a draft would pass as a real girlfriend DM given the thread.
Does NOT replace scheme_guard (money/locks/delivery). Toggle: REPLY_SUPERVISOR=1.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from openai import OpenAI

from config import config

if TYPE_CHECKING:
    from core.reply_sanitize import RewriteBudget
    from core.reply_types import AssembledTurn

_CLIENT: Optional[OpenAI] = None

RUBRIC = """You supervise Emma, a Fanvue creator chatting with fans like a real girlfriend on WhatsApp.

Judge ONLY whether her DRAFT reply is OK to send right now.

Do NOT enforce technical business rules (exact PPV price, lock SKUs, vault catalog).
Judge human feel:
- Does she answer what HE actually said last?
- Right vibe for the moment (upset boundary / skeptical pushback / flirty / chill)?
- Short natural DM — not essay, customer support, marketing, or scripted stamp?
- Bot tells: love-bombing a stranger, ignoring his refusal, pushing pics/sell when he's angry,
  generic filler, doubling down when he asked her to stop, sounding like an AI assistant.

Return ONLY valid JSON:
{"ok": true|false, "why": "max 18 words", "rewrite_hint": "one concrete fix if ok=false else empty"}

ok=true if a real fan would accept this as natural.
ok=false if it would feel wrong, robotic, pushy, or off-topic — even if grammatically fine."""


@dataclass
class SupervisorVerdict:
    ok: bool
    why: str = ""
    rewrite_hint: str = ""


def enabled() -> bool:
    return bool(getattr(config, "REPLY_SUPERVISOR", False))


def _client() -> OpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
        )
    return _CLIENT


def _parse(raw: str) -> Optional[SupervisorVerdict]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    return SupervisorVerdict(
        ok=bool(data.get("ok")),
        why=str(data.get("why") or "")[:120],
        rewrite_hint=str(data.get("rewrite_hint") or "")[:200],
    )


def _thread_snippet(turns: Optional[List[Dict[str, Any]]], *, limit: int = 10) -> str:
    lines: List[str] = []
    for t in (turns or [])[-limit:]:
        role = "FAN" if (t.get("role") or "") == "user" else "EMMA"
        body = (t.get("content") or "").strip().replace("\n", " / ")
        if body:
            lines.append(f"{role}: {body[:220]}")
    return "\n".join(lines) if lines else "(no history)"


def _context_note(assembled: "AssembledTurn") -> str:
    from core.fan_pushback import thread_in_boundary_mode, thread_in_pushback_mode

    mem = {}
    if assembled.fan_uuid:
        from core import fan_memory

        mem = fan_memory.get(assembled.fan_uuid) or {}
    bits: List[str] = []
    if thread_in_boundary_mode(
        assembled.fan_message or "", assembled.turns, mem
    ):
        bits.append("fan set a boundary / refused pics — warm only, no sell/pic pressure")
    elif thread_in_pushback_mode(
        assembled.fan_message or "", assembled.turns, mem
    ):
        bits.append("fan skeptical / thinks she's a bot — human reassurance, no heat")
    if assembled.offer and float(assembled.offer.get("price") or 0) > 0:
        bits.append("a paid photo may attach with her text")
    elif assembled.voice_will_send:
        bits.append("a voice note attaches after text — keep typed bubble short")
    return "; ".join(bits) if bits else "normal chat"


def evaluate_reply(
    reply: str,
    assembled: "AssembledTurn",
) -> Optional[SupervisorVerdict]:
    """One fast-model call. Returns None on API/parse failure (fail-open)."""
    if not (reply or "").strip():
        return SupervisorVerdict(ok=False, why="empty draft")

    model = (
        getattr(config, "REPLY_SUPERVISOR_MODEL", None)
        or getattr(config, "DEEPSEEK_FAST_MODEL", None)
        or config.DEEPSEEK_MODEL
    )
    user = (
        f"CONTEXT: {_context_note(assembled)}\n\n"
        f"RECENT THREAD:\n{_thread_snippet(assembled.turns)}\n\n"
        f"HIS LAST MESSAGE:\n{(assembled.fan_message or '').strip()[:400]}\n\n"
        f"EMMA DRAFT:\n{(reply or '').strip()[:500]}\n\n"
        "JSON:"
    )
    kwargs: Dict[str, Any] = dict(
        model=model,
        messages=[
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": user},
        ],
        temperature=0.25,
        max_tokens=160,
    )
    if getattr(config, "DEEPSEEK_DISABLE_THINKING", False):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}

    try:
        resp = _client().chat.completions.create(**kwargs)
        return _parse(resp.choices[0].message.content or "")
    except Exception as exc:
        print(f"   ⚠️ reply-supervisor failed: {exc}")
        return None


def _pick_fallback(assembled: "AssembledTurn", *, banned: set[str]) -> str:
    from core.fan_pushback import (
        pick_photo_refusal_fallback,
        pick_pushback_fallback,
        thread_in_boundary_mode,
        thread_in_pushback_mode,
    )
    from core import fan_memory

    mem = fan_memory.get(assembled.fan_uuid) or {} if assembled.fan_uuid else {}
    if thread_in_boundary_mode(
        assembled.fan_message or "", assembled.turns, mem
    ):
        return pick_photo_refusal_fallback(banned=banned)
    if thread_in_pushback_mode(
        assembled.fan_message or "", assembled.turns, mem
    ):
        return pick_pushback_fallback(assembled.fan_message or "", banned=banned)
    return "hey… tell me what you meant by that"


def supervise_reply(
    reply: str,
    assembled: "AssembledTurn",
    *,
    call,
    budget: Optional["RewriteBudget"] = None,
) -> str:
    """
    Final humanity gate. On reject: one rewrite if budget allows, else fallback.
    Fail-open if the supervisor API is down.
    """
    if not enabled():
        return reply

    verdict = evaluate_reply(reply, assembled)
    if verdict is None:
        return reply
    if verdict.ok:
        return reply

    print(f"   🛡 supervisor reject: {verdict.why or 'bad vibe'}")

    hint = (verdict.rewrite_hint or verdict.why or "").strip()
    if hint and budget is not None and budget.can_spend():
        fix = budget.spend(
            "supervisor",
            call,
            assembled.messages
            + [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": (
                        f"SUPERVISOR REJECT — fix and resend. {hint} "
                        "Keep ONE short WhatsApp bubble (~90 chars). "
                        "React to his LAST message. No sell unless context says attach."
                    ),
                },
            ],
        )
        if (fix or "").strip():
            recheck = evaluate_reply(fix, assembled)
            if recheck is None or recheck.ok:
                print("   🛡 supervisor rewrite accepted")
                return (fix or "").strip()

    from core.reply_sanitize import _norm_bubble

    banned = {
        _norm_bubble(str(t.get("content") or ""))
        for t in (assembled.turns or [])[-8:]
    }
    fb = _pick_fallback(assembled, banned=banned)
    print(f"   🛡 supervisor fallback → {fb!r}")
    return fb
