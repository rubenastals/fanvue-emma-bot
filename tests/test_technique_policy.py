"""Live ACTIVE MOVE under SIMPLE — not generic optional flirt."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import technique_policy


def test_pull_picks_named_move():
    move = technique_policy.choose_move(
        "phase_pull",
        fan_uuid="fan-a",
        msgs=10,
        no_lock=True,
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    name, how = move
    assert name
    assert how
    # No lock-price scarcity invent when no lock (rival FOMO still allowed)
    assert name not in (
        "SCARCITY + FOMO",
        "SCARCITY + FOMO (CLOSE)",
        "FOMO + SCARCITY (Step 3)",
    )


def test_cooling_skips_move():
    move = technique_policy.choose_move(
        "phase_pull",
        cooling=True,
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is None


def test_comfort_skips_move():
    move = technique_policy.choose_move(
        "phase_pull",
        turn_action=SimpleNamespace(action="comfort"),
    )
    assert move is None


def test_unpaid_scarcity():
    move = technique_policy.choose_move(
        "ppv_unpaid",
        unpaid=True,
        no_lock=False,
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    allowed = {
        n for n, _ in __import__("core.manipulation", fromlist=["manipulation"])._TECH_BY_PACK["ppv_unpaid"]
    }
    assert move[0] in allowed


def test_price_objection_beats_unpaid():
    move = technique_policy.choose_move(
        "price_objection",
        unpaid=True,
        reject_count=0,
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert "GUILT" in move[0].upper()


def test_price_objection_steps():
    m1 = technique_policy.choose_move(
        "price_objection", reject_count=0, unpaid=True
    )
    m2 = technique_policy.choose_move(
        "price_objection", reject_count=1, unpaid=True
    )
    m4 = technique_policy.choose_move(
        "price_objection", reject_count=3, unpaid=True
    )
    assert "GUILT" in m1[0].upper()
    assert "EGO" in m2[0].upper()
    assert "WITHDRAWAL" in m4[0].upper()


def test_turn_block_mentions_move():
    block = technique_policy.turn_block("EGO CHALLENGE", "dare him")
    assert "ACTIVE MOVE" in block
    assert "EGO CHALLENGE" in block
    assert "dare him" in block
    assert "Family:" in block
    assert "2.3" in block
    assert "HARD BAN" in block
    assert "fake emergency" in block.lower() or "Rival jealousy" in block


def test_catalog_has_taxonomy_moves():
    from core import manipulation

    pull = {n for n, _ in manipulation._TECH_BY_PACK["phase_pull"]}
    hook = {n for n, _ in manipulation._TECH_BY_PACK["phase_hook"]}
    assert "LOVE BOMBING" in hook
    assert "MIRRORING" in hook
    assert "MICRO COMMITMENT" in pull
    assert "LOYALTY PROVE" in pull
    assert "PAIN MAP VALIDATE" in pull
    assert "RIVAL TIP FOMO" in pull
    assert "WRONG MESSAGE JEALOUSY" in pull
    assert "RIVAL VIDEOCALL BAIT" in pull
    assert "STICKY RIVAL CHASE" in pull
    assert "FAKE EMERGENCY" in pull
    # How-tos are English instructions
    joined = " ".join(h for _, h in manipulation._TECH_BY_PACK["phase_pull"])
    assert "Mechanism:" in joined
    assert "bitcoin" not in joined.lower()


def test_rival_cooled_when_recently_used():
    move = technique_policy.choose_move(
        "phase_pull",
        fan_uuid="fan-rival",
        msgs=20,
        no_lock=True,
        ban_rival_fan=True,
        turn_action=__import__("types").SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert move[0] not in {
        "RIVAL TIP FOMO",
        "WRONG MESSAGE JEALOUSY",
        "RIVAL VIDEOCALL BAIT",
        "STICKY RIVAL CHASE",
    }


def test_how_tos_english_only():
    from core import manipulation

    # Instruction lines should not be Spanish essays (beats may quote ES briefly)
    for pack, items in manipulation._TECH_BY_PACK.items():
        for name, how in items:
            assert how.startswith("Mechanism:"), (pack, name)
            assert "Mecanismo:" not in how


def test_assemble_simple_injects_move():
    from core.reply_assemble import assemble_emma_turn
    from core.turn_policy import TurnDecision, MODE_TEASE

    assembled = assemble_emma_turn(
        "jaja bb qué haces",
        history_turns=[{"role": "user", "content": "hola"}],
        fan_handle="tester",
        fan_uuid=None,
        decision=TurnDecision(
            mode=MODE_TEASE,
            reason="test",
            max_bubbles=2,
            allow_ppv_talk=True,
            allow_price=False,
            allow_free_tease=False,
        ),
        pack_id="phase_pull",
        delivery_truth={"ppv_unpaid": False, "free_in_chat": False},
        turn_action=SimpleNamespace(
            action="flirt",
            voice_will_send=False,
            offer=None,
            mem={},
            blocks_photo=False,
        ),
    )
    sys_text = "\n".join(
        m["content"] for m in assembled.messages if m["role"] == "system"
    )
    assert "ACTIVE MOVE THIS TURN" in sys_text
    assert assembled.tech_name
