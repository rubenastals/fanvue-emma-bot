"""
Historical sins — forced regressions from production failures.

Each scenario replays a fan message (or bad Emma draft) that burned us before.
No LLM: router → selector → assemble facts → sanitize belts.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, List, Optional, Set

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import fan_memory, scheme_guard as sg
from core.intent_router import route
from core.offer_selector import choose_offer
from core.reply_engine import (
    _claims_unconfirmed_delivery,
    _enforce_delivery_truth,
    _fix_invented_wait_minutes,
)
from core.reply_sanitize import apply_post_draft
from core.fan_pushback import fan_has_pushback, reply_invents_sunglasses


def _mem(**kw):
    base = {
        "messages": 20,
        "status": "warm",
        "total_spent": 0.0,
        "purchases": 0,
        "free_teases_sent": 1,
        "sent_media_uuids": [],
    }
    base.update(kw)
    return base


def _assembled(
    *,
    fan_message: str,
    bad_draft: str,
    turns: Optional[list] = None,
    fan_uuid: str = "sin-fan",
    offer=None,
    lock_active: bool = False,
    no_lock: bool = True,
    unpaid_gate: bool = False,
    never_bought: bool = True,
    fan_saw_bluff: bool = False,
):
    turns = turns or [{"role": "user", "content": fan_message}]
    return SimpleNamespace(
        messages=[],
        decision=SimpleNamespace(mode="rapport", pack_id="phase_pull"),
        pack_id="phase_pull",
        tech_name="BOND",
        phase_name="",
        want_spanish=False,
        fan_uuid=fan_uuid,
        fan_handle="tester",
        fan_message=fan_message,
        turns=turns,
        offer=offer,
        ppv_status=None,
        voice_will_send=False,
        lock_active=lock_active,
        no_lock=no_lock,
        status_active=lock_active,
        unpaid_gate=unpaid_gate,
        never_bought=never_bought,
        fan_saw_bluff=fan_saw_bluff,
    )


@dataclass
class SinScenario:
    id: str
    thread: str
    fan_message: str
    mem: dict = field(default_factory=lambda: _mem())
    delivery_truth: Optional[dict] = None
    bad_draft: Optional[str] = None
    expected_packs: Optional[Set[str]] = None
    forbid_price: bool = False
    forbid_ppv_talk: bool = False
    forbid_sell: bool = False
    sell_paused: bool = False
    sanitize_must_not: Optional[List[str]] = None
    guard_check: Optional[Callable[[], None]] = None
    assemble_must: Optional[List[str]] = None


SCENARIOS: List[SinScenario] = [
    # ── Dan: soft decline / sell cooldown ─────────────────────────────
    SinScenario(
        id="dan_bills",
        thread="Dan",
        fan_message="I can't open it yet, as I need to pay my bills first",
        delivery_truth={"ppv_unpaid": True},
        expected_packs={"ppv_unpaid"},
    ),
    SinScenario(
        id="dan_cant_right_now",
        thread="Dan",
        fan_message="I can't right now",
        delivery_truth={"ppv_unpaid": True},
        expected_packs={"ppv_unpaid", "phase_pull"},
    ),
    SinScenario(
        id="dan_love_bomb_draft",
        thread="Dan",
        fan_message="Absolutely",
        bad_draft=(
            "mm I like having you here… only girl in the world rn, "
            "got me feeling soft and special 💕"
        ),
    ),
    SinScenario(
        id="dan_cold_hey_no_attach",
        thread="Dan",
        fan_message="hey",
        mem=_mem(
            last_reject_at=(datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
        ),
        forbid_sell=True,
    ),
    # ── Tommy: pushback / vision ───────────────────────────────────────
    SinScenario(
        id="tommy_ai_robot",
        thread="Tommy",
        fan_message="Stop using the AI feature",
        bad_draft="fuck... now I'm just sitting here in my sports bra wondering what you'd do",
        sanitize_must_not=["sports bra", "wondering what you'd"],
    ),
    SinScenario(
        id="tommy_flattery_skeptic",
        thread="Tommy",
        fan_message="That's what you tell all the boys lol",
        guard_check=lambda: (_assert(fan_has_pushback("That's what you tell all the boys lol"))),
    ),
    SinScenario(
        id="tommy_sunglasses_hallucination",
        thread="Tommy",
        fan_message="Girl, neither pic has me in sunglasses?",
        guard_check=lambda: _assert(
            reply_invents_sunglasses(
                "send me one without the sunglasses babe",
                "A man with gray hair, mountains behind. CLASS: fan_male_sfw",
            )
        ),
    ),
    # ── Juan: cold sell / quotes / grabar ─────────────────────────────
    SinScenario(
        id="juan_fotos_para_mi",
        thread="Juan",
        fan_message="pero fotos para mi?",
        expected_packs={"phase_pull", "phase_spiral", "ask_free_first"},
        forbid_price=True,
        forbid_sell=True,
    ),
    SinScenario(
        id="juan_emotional_unpaid",
        thread="Juan",
        fan_message="prefieres hablar antes? te molestó mucho tu mama?",
        delivery_truth={"ppv_unpaid": True},
        expected_packs={"ppv_unpaid", "phase_pull"},
    ),
    SinScenario(
        id="juan_grabar_not_video",
        thread="Juan",
        fan_message="tengo que irme a grabar contenido",
        guard_check=lambda: _assert(
            not sg.invented_video_claim(
                "Grabar contenido para mi página, cielo... ya sabes, fotitos"
            )
        ),
    ),
    SinScenario(
        id="juan_left_photo_bluff",
        thread="Juan",
        fan_message="no me has mandado ninguna foto",
        bad_draft="y ni siquiera has abierto la foto que te dejé... así que no te quejes",
        guard_check=lambda: _assert(
            sg.claims_left_photo(
                "y ni siquiera has abierto la foto que te dejé... así que no te quejes"
            )
        ),
    ),
    # ── Delivery lies (H0 gate) ───────────────────────────────────────
    SinScenario(
        id="delivery_fake_sent",
        thread="delivery",
        fan_message="no me has mandado ninguna foto",
        bad_draft="Ya te envié la foto, está en tu bandeja 😏",
        guard_check=lambda: _assert(
            _claims_unconfirmed_delivery("Ya te envié la foto, está en tu bandeja 😏")
            and not _claims_unconfirmed_delivery(
                _enforce_delivery_truth(
                    "Ya te envié la foto, está en tu bandeja 😏",
                    media_attached=False,
                    want_spanish=True,
                )
            )
        ),
    ),
    SinScenario(
        id="delivery_invented_wait",
        thread="delivery",
        fan_message="?",
        bad_draft="Llevo 27 minutos esperando que abras el candado",
        guard_check=lambda: _assert(
            "27"
            not in _fix_invented_wait_minutes(
                "Llevo 27 minutos esperando que abras el candado", minutes_ago=4
            )
        ),
    ),
    # ── Purchase bluff ────────────────────────────────────────────────
    SinScenario(
        id="bluff_fan_liked_photo",
        thread="bluff",
        fan_message="me ha gustado mucho la ultima foto",
        guard_check=lambda: _assert(sg.fan_claims_saw_ppv("me ha gustado mucho la ultima foto")),
    ),
    SinScenario(
        id="bluff_emma_validates_unseen",
        thread="bluff",
        fan_message="me gustó esa foto",
        bad_draft="glad you liked it — that was just a tease",
        guard_check=lambda: _assert(
            sg.validates_unseen_ppv("glad you liked it — that was just a tease")
        ),
    ),
    # ── Boundary / privacy ────────────────────────────────────────────
    SinScenario(
        id="boundary_stop_pics",
        thread="boundary",
        fan_message="being pushy like that could be reported, please stop asking me for pictures",
        expected_packs={"phase_pull"},
        forbid_sell=True,
    ),
    SinScenario(
        id="boundary_soft_no",
        thread="boundary",
        fan_message="no, sorry",
        delivery_truth={"ppv_unpaid": True},
        expected_packs={"ppv_unpaid", "phase_pull"},
    ),
    # ── Silence guilt loops (belts off — playbook owns tone) ───────────
    SinScenario(
        id="guilt_silence_reproach",
        thread="loops",
        fan_message="I was just joking... I get nervous around a girl as hot as you.",
        bad_draft="because I actually opened up and now you're just... quiet? 💔",
    ),
    SinScenario(
        id="guilt_poof_gone",
        thread="loops",
        fan_message="haha you're funny",
        bad_draft=(
            "most guys don't even make it this far tbh... "
            "I say something real and poof they're gone"
        ),
    ),
]


def _assert(cond: bool, msg: str = "") -> None:
    if not cond:
        raise AssertionError(msg or "assertion failed")


def _run_router(s: SinScenario):
    r = route(s.mem, s.fan_message, delivery_truth=s.delivery_truth or {})
    if s.expected_packs is not None:
        _assert(r.pack_id in s.expected_packs, f"pack={r.pack_id} not in {s.expected_packs}")
    if s.forbid_price:
        _assert(not r.decision.allow_price, "allow_price should be False")
    if s.forbid_ppv_talk:
        _assert(not r.decision.allow_ppv_talk, "allow_ppv_talk should be False")
    return r


def _run_selector(s: SinScenario, route_result=None) -> None:
    if not s.forbid_sell:
        return
    facts = route_result.facts if route_result is not None else None
    choice = choose_offer(
        s.mem,
        s.fan_message,
        history_turns=[{"role": "user", "content": s.fan_message}],
        facts=facts,
    )
    _assert(not choice.sell_now, f"selector sold: {choice.reason}")


def _run_sell_pause(s: SinScenario) -> None:
    if not s.sell_paused:
        return
    from core.sell_gate import chill_turn

    _assert(chill_turn(s.mem, s.fan_message))
    attach, _ = __import__(
        "core.sell_gate", fromlist=["should_attach_ppv"]
    ).should_attach_ppv(s.mem, s.fan_message)
    _assert(not attach)


def _run_assemble(s: SinScenario, monkeypatch=None) -> None:
    if not s.assemble_must:
        return
    from core.reply_assemble import assemble_emma_turn

    if monkeypatch is not None:
        monkeypatch.setattr(fan_memory, "get", lambda _u: s.mem)
        monkeypatch.setattr(
            fan_memory, "sell_pressure_paused", lambda _m, **kw: True
        )
    assembled = assemble_emma_turn(
        s.fan_message,
        history_turns=[{"role": "user", "content": s.fan_message}],
        fan_uuid="sin-assemble",
        fan_handle="tester",
    )
    blob = "\n".join(m["content"] for m in assembled.messages if m["role"] == "system")
    for needle in s.assemble_must:
        _assert(needle in blob, f"missing {needle!r} in assemble")


def _run_sanitize(s: SinScenario) -> None:
    if not s.bad_draft or not s.sanitize_must_not:
        return
    out, _ = apply_post_draft(
        s.bad_draft,
        _assembled(fan_message=s.fan_message, bad_draft=s.bad_draft),
        call=lambda _m: "hey… tell me more",
    )
    low = out.lower()
    for bad in s.sanitize_must_not:
        _assert(bad.lower() not in low, f"sanitize still contains {bad!r}: {out!r}")


def run_scenario(s: SinScenario, *, monkeypatch=None, skip_assemble: bool = False) -> None:
    r = _run_router(s)
    _run_selector(s, r)
    _run_sell_pause(s)
    if s.guard_check:
        s.guard_check()
    _run_sanitize(s)
    if not skip_assemble:
        _run_assemble(s, monkeypatch=monkeypatch)


# ── pytest entrypoints ────────────────────────────────────────────────


def test_historical_sin_matrix():
    """All historical sins must pass without LLM."""
    failures = []
    for s in SCENARIOS:
        try:
            run_scenario(s)
        except Exception as e:
            failures.append(f"{s.id} ({s.thread}): {e}")
    if failures:
        raise AssertionError(
            f"{len(failures)}/{len(SCENARIOS)} sins failed:\n"
            + "\n".join(f"  - {f}" for f in failures)
        )


def test_historical_sin_dan_bills_chill(monkeypatch):
    s = next(x for x in SCENARIOS if x.id == "dan_bills")
    from core.sell_gate import chill_turn

    assert not chill_turn(s.mem, s.fan_message)


# ── CLI report ────────────────────────────────────────────────────────

if __name__ == "__main__":
    ok, fail = 0, []
    print(f"Historical sins matrix ({len(SCENARIOS)} scenarios)\n")
    print(f"{'ID':<28} {'THREAD':<10} STATUS")
    print("-" * 50)
    for s in SCENARIOS:
        try:
            run_scenario(s)
            print(f"{s.id:<28} {s.thread:<10} OK")
            ok += 1
        except Exception as e:
            print(f"{s.id:<28} {s.thread:<10} FAIL — {e}")
            fail.append(s.id)
    print("-" * 50)
    print(f"OK {ok}/{len(SCENARIOS)}")
    if fail:
        print("FAILED:", ", ".join(fail))
        raise SystemExit(1)
