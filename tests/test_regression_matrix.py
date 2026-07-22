"""
No-regression matrix for the SIMPLE live brain (audit R6).

Cross-seam coverage for R1–R5 + A-series:
voice FSM, rewrite cap, quarantine, TurnAction, bubbles, sell/bluff, flags.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from config import config
from core import (
    prompt_core,
    prompt_layers,
    quarantine,
    scheme_guard as sg,
    strategy_prompt,
)
from core.intent_router import route
from core.reply_engine import (
    RewriteBudget,
    _enforce_delivery_truth,
    _fix_invented_wait_minutes,
    _strip_wrong_prices,
    looks_incomplete_text,
    _trim_dangling_clause,
)
from core.turn_action import (
    ACTION_ATTACH_PPV,
    ACTION_COMFORT,
    ACTION_FLIRT,
    ACTION_SEND_VOICE,
    action_prompt_line,
    classify_turn_action,
    wants_comfort,
)


def _mem(**kwargs):
    base = {
        "messages": 10,
        "status": "warm",
        "free_teases_sent": 0,
        "offers_today": 0,
        "total_spent": 0,
        "purchases": 0,
    }
    base.update(kwargs)
    return base


# ── A1 / production flags ─────────────────────────────────────────────


def test_production_live_flags():
    assert config.SIMPLE_PROMPT is True
    assert config.LEAN_CREATIVE is True
    assert config.REPLY_V2 is False
    assert config.INJECT_LESSONS is False
    assert config.PHASE_ANALYST is False
    assert int(getattr(config, "MAX_CREATIVE_REWRITES", 1)) == 1
    # Do NOT blindly inflate history (Copilot anti-pattern)
    assert int(config.HISTORY_MAX_MESSAGES) <= 64
    assert int(config.HISTORY_HOURS) <= 72


def test_persona_has_priority_ladder():
    persona = prompt_core.get_active_persona()
    assert "PRIORITY THIS TURN" in persona
    assert "SELL STATUS" in persona
    assert "ATTACHING" in persona
    assert "Emma: Mmm" not in persona
    assert "Never start messages with \"Ay…\", \"Mmm…\"" in persona
    assert "WHATSAPP VOICE" in persona
    assert "EARLY CONVERSATION STRATEGY" in persona or "look how filthy" in persona
    assert "caro" in persona.lower() and "papi" in persona.lower()


def test_truth_state_cooling_skips_technique():
    ts = strategy_prompt.truth_state(cooling=True, lock_active=False)
    assert "COOLING" in ts
    assert "skip TECHNIQUE ENGINE" in ts


# ── A4 / R2 fallbacks ─────────────────────────────────────────────────


def test_fallbacks_obey_style_bans():
    samples = [
        sg.fallback_purchase_bluff(want_spanish=True, lock_still_active=True),
        sg.fallback_purchase_bluff(want_spanish=False, lock_still_active=False),
        sg.fallback_no_lock(want_spanish=True),
        sg.fallback_no_lock(want_spanish=False),
        sg.fallback_photos_only(want_spanish=True, real_price=7.0),
        sg.fallback_photos_only(want_spanish=False, real_price=None),
        sg.fallback_ghost_promise(want_spanish=True),
        sg.fallback_ghost_promise(want_spanish=False),
        sg.fallback_blame_own_it(want_spanish=True),
        sg.fallback_blame_own_it(want_spanish=False),
        sg.forced_paid_sell_line(price=9, want_spanish=True, label="tits"),
        sg.forced_paid_sell_line(price=9, want_spanish=False, label="ass"),
    ]
    for text in samples:
        assert sg.fallback_obeys_style_bans(text), text
        assert not text.lower().startswith("mmm")
        assert not text.lower().startswith("ay")


def test_fallbacks_do_not_retrigger_own_detectors():
    """R2: deterministic fallbacks must be shippable without another rewrite."""
    assert not sg.invented_lock_claim(
        sg.fallback_no_lock(want_spanish=True), lock_active=False
    )
    assert not sg.invented_video_claim(
        sg.fallback_photos_only(want_spanish=True, real_price=None)
    )
    assert not sg.invented_video_claim(
        sg.fallback_photos_only(want_spanish=False, real_price=12.0)
    )
    ghost = sg.fallback_ghost_promise(want_spanish=True)
    assert not sg.ghost_media_promise(ghost, media_attached=False)
    blame = sg.fallback_blame_own_it(want_spanish=True)
    assert not sg.blame_after_ghost(blame, media_attached=False)


def test_hard_lies_deterministic_strips():
    dirty = "Ya te envié la foto, está en tu bandeja 😏"
    from core.reply_engine import _claims_unconfirmed_delivery

    assert _claims_unconfirmed_delivery(dirty)
    clean = _enforce_delivery_truth(dirty, media_attached=False, want_spanish=True)
    assert not _claims_unconfirmed_delivery(clean)

    wait = _fix_invented_wait_minutes(
        "Llevo 27 minutos esperando que abras el candado", minutes_ago=4
    )
    assert "27" not in wait
    assert not sg.invented_lock_wait_minutes(wait, minutes_ago=4)

    priced = _strip_wrong_prices("Ábrela por $9 bebé", real_price=40.0)
    assert "$40" in priced and "$9" not in priced


def test_rewrite_budget_one_llm_max():
    calls = []

    def fake_call(msgs):
        calls.append(1)
        return "ok"

    rw = RewriteBudget(max_extra=1)
    assert rw.spend("lang", fake_call, []) == "ok"
    assert rw.spend("grammar", fake_call, []) is None
    assert len(calls) == 1


# ── sell / unpaid ─────────────────────────────────────────────────────


def test_sell_commit_alignment():
    assert sg.paid_offer_reply_aligned(
        "Solo para ti… esta foto mía, $8 — ábrela si de verdad quieres verme así"
    )
    assert not sg.paid_offer_reply_aligned(
        "mándame una foto tuya primero baby"
    )
    line = sg.forced_paid_sell_line(price=8, want_spanish=True, label="tits")
    assert sg.paid_offer_reply_aligned(line)
    assert "$8" in line


def test_unpaid_gate_pack():
    r = route(
        _mem(free_teases_sent=1),
        "hola",
        delivery_truth={"ppv_unpaid": True},
    )
    assert r.pack_id == "ppv_unpaid"
    assert r.facts.hard_pack == "ppv_unpaid"
    assert r.decision.allow_price is False


# ── R1 + R5 + A8: voice / comfort / PPV ───────────────────────────────


def test_voice_action_beats_paid_ppv():
    offer = {"price": 40, "level": 2, "label": "tits", "media_uuid": "x"}
    ta = classify_turn_action(
        voice_ok=True,
        voice_why="FSM open_voice → send",
        blocks_photo=True,
        offer=offer,
    )
    assert ta.action == ACTION_SEND_VOICE
    assert ta.offer is None
    assert ta.blocks_photo


def test_voice_debt_blocks_ppv_without_send():
    """A8: audio API down / cannot send → still never attach $40."""
    ta = classify_turn_action(
        voice_ok=False,
        voice_why="photo-blocked (debt)",
        blocks_photo=True,
        offer={"price": 40, "level": 2, "label": "t", "media_uuid": "m"},
    )
    assert ta.action == ACTION_FLIRT
    assert ta.offer is None
    assert ta.blocks_photo


def test_comfort_beats_sell():
    assert wants_comfort("se me murió mi perro estoy muy mal")
    ta = classify_turn_action(
        voice_ok=False,
        comfort=True,
        offer={"price": 9, "level": 1, "label": "a", "media_uuid": "m"},
    )
    assert ta.action == ACTION_COMFORT
    assert ta.offer is None


def test_action_prompt_covers_protocol():
    voice = classify_turn_action(voice_ok=True, voice_why="ask")
    vline = action_prompt_line(
        voice, mem={"open_commitment": {"type": "voice", "hits": 3}}
    )
    assert "pídemelo" in vline.lower() or "COMMITMENT" in vline

    comfort = classify_turn_action(voice_ok=False, comfort=True)
    assert "comfort" in action_prompt_line(comfort).lower()

    ppv = classify_turn_action(
        voice_ok=False,
        offer={"price": 40, "level": 2, "label": "t", "media_uuid": "m"},
    )
    assert ppv.action == ACTION_ATTACH_PPV
    assert "$40" in action_prompt_line(ppv)


# ── A5 / A6 bubbles + continuity ──────────────────────────────────────


def test_incomplete_bubbles_trim():
    assert looks_incomplete_text("estaba pensando en ti y")
    out = _trim_dangling_clause("Solo para ti, bebé. Quería decirte que")
    assert out.endswith(".")
    assert not looks_incomplete_text(out)


def test_thread_beat_uses_recent_not_stale_summary():
    turns = [
        {"role": "user", "content": "my dog is sick today"},
        {"role": "assistant", "content": "aw baby I'm sorry"},
        {"role": "user", "content": "yeah I'm worried"},
    ]
    mem = {"summary": "He likes cars and soccer", "facts": ["has a dog named Max"]}
    beat = sg.thread_beat_block(turns, mem)
    assert "Recent thread:" in beat
    assert "dog" in beat.lower() or "worried" in beat.lower()
    assert "He likes cars" not in beat


def test_prompt_layers_budget_and_order():
    messages, sizes = prompt_layers.build_system_layers(
        card_block="CLIENT CARD:\nname=Test",
        language_block="LANGUAGE: English",
        time_block="TIME: afternoon",
        name_block="ADDRESSING: baby",
        turn_blocks=[
            "TRUTH STATE THIS TURN:\n- NO lock",
            "SELL STATUS: NONE",
            "AUDIO THIS TURN: NO voice note",
        ],
        core_prompt="CORE PERSONA TEXT",
    )
    assert messages[0]["content"].startswith("CORE")
    assert any("CLIENT CARD" in m["content"] for m in messages)
    assert sizes["turn"] <= prompt_layers.BUDGET_TURN_SYSTEM
    assert sizes["core"] <= prompt_layers.BUDGET_CORE


# ── R3 quarantine ─────────────────────────────────────────────────────


def test_quarantine_markers_and_no_strategy_essay_call():
    assert not quarantine.missing_markers()
    facade = (_ROOT / "core" / "reply_engine.py").read_text(encoding="utf-8")
    assemble = (_ROOT / "core" / "reply_assemble.py").read_text(encoding="utf-8")
    assert "strategy_block(" not in facade
    assert "strategy_block(" not in assemble
    assert "truth_state" in assemble
    autofix = (_ROOT / "core" / "auto_fix.py").read_text(encoding="utf-8")
    assert "personas/emma.md" in autofix
    assert "Do NOT edit quarantined dead brains" in autofix


def test_banned_fallback_open_detector():
    assert not sg.fallback_obeys_style_bans("Mmm… mentiroso 😏")
    assert not sg.fallback_obeys_style_bans("Ay bebé ven aquí")
    assert not sg.fallback_obeys_style_bans("hola papi qué tal")
    assert sg.fallback_obeys_style_bans("Mentiroso 😏 no la abriste")


def test_audit_board_has_no_conflict_markers():
    text = (_ROOT / "docs" / "AUDIT_COMPLETION.md").read_text(encoding="utf-8")
    assert "<<<<<<<" not in text
    assert ">>>>>>>" not in text
    assert "=======" not in text
    assert "R2" in text and "R5" in text


def test_r4_reply_seams_exist():
    """Facade stays thin; assemble / sanitize own the heavy logic."""
    assert (_ROOT / "core" / "reply_assemble.py").is_file()
    assert (_ROOT / "core" / "reply_sanitize.py").is_file()
    assert (_ROOT / "core" / "reply_types.py").is_file()
    facade = (_ROOT / "core" / "reply_engine.py").read_text(encoding="utf-8")
    assert "assemble_emma_turn" in facade
    assert "apply_post_draft" in facade
    assert "def generate_emma_reply" in facade
    # Facade should not still be the god-object
    assert facade.count("\n") < 250


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("ok")
