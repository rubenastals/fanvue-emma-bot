"""Strategic ACTIVE MOVE under SIMPLE — context-aware, not random flirt."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import technique_policy
from core.technique_policy import ActiveMove


def test_pull_picks_named_move():
    move = technique_policy.choose_move(
        "phase_pull",
        fan_uuid="fan-a",
        msgs=10,
        no_lock=True,
        mem={"messages": 10, "total_spent": 0, "purchases": 0},
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert move.name
    assert move.how
    assert move.why
    assert move.name not in (
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


def test_unpaid_prefers_pressure():
    move = technique_policy.choose_move(
        "ppv_unpaid",
        unpaid=True,
        no_lock=False,
        mem={"messages": 12, "total_spent": 0},
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    allowed = {
        n
        for n, _ in __import__(
            "core.manipulation", fromlist=["m"]
        )._TECH_BY_PACK["ppv_unpaid"]
    }
    assert move.name in allowed


def test_price_objection_beats_unpaid():
    move = technique_policy.choose_move(
        "price_objection",
        unpaid=True,
        reject_count=0,
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert "GUILT" in move.name.upper()
    assert "objection-step" in move.why


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
    assert "GUILT" in m1.name.upper()
    assert "EGO" in m2.name.upper()
    assert "WITHDRAWAL" in m4.name.upper()


def test_early_chat_avoids_emergency():
    m = technique_policy.choose_move(
        "phase_pull",
        fan_uuid="early-bond",
        msgs=2,
        mem={"messages": 2, "total_spent": 0},
        no_lock=True,
        ban_rival_fan=True,
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert m is not None
    assert m.name != "FAKE EMERGENCY"
    assert "EMERGENCY" not in m.name
    assert m.name not in manipulation_rivals()


def manipulation_rivals():
    from core import manipulation

    return set(manipulation._RIVAL_TECHS)


def test_turn_block_mentions_move():
    move = ActiveMove(
        name="EGO CHALLENGE",
        how="dare him",
        why="heat-close|score=20",
        family_id="2.3",
        principle="competition / status",
    )
    block = technique_policy.turn_block(move)
    assert "ACTIVE MOVE" in block
    assert "EGO CHALLENGE" in block
    assert "dare him" in block
    assert "Family:" in block
    assert "2.3" in block
    assert "Why this move:" in block
    assert "HARD BAN" in block


def test_catalog_has_taxonomy_moves():
    from core import manipulation

    pull = {n for n, _ in manipulation._TECH_BY_PACK["phase_pull"]}
    hook = {n for n, _ in manipulation._TECH_BY_PACK["phase_hook"]}
    assert "LOVE BOMBING" in hook
    assert "MIRRORING" in hook
    assert "MICRO COMMITMENT" in pull
    assert "RIVAL TIP FOMO" in pull
    assert "FAKE EMERGENCY" in pull


def test_rival_cooled_when_recently_used():
    move = technique_policy.choose_move(
        "phase_pull",
        fan_uuid="fan-rival",
        msgs=20,
        no_lock=True,
        ban_rival_fan=True,
        mem={"messages": 20, "total_spent": 0},
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert move is not None
    assert move.name not in {
        "RIVAL TIP FOMO",
        "WRONG MESSAGE JEALOUSY",
        "RIVAL VIDEOCALL BAIT",
        "STICKY RIVAL CHASE",
    }


def test_how_tos_english_only():
    from core import manipulation

    for pack, items in manipulation._TECH_BY_PACK.items():
        for name, how in items:
            assert how.startswith("Mechanism:"), (pack, name)
            assert "Mecanismo:" not in how


def test_reply_hits_move_signals():
    assert technique_policy.reply_hits_move(
        "another guy keeps texting me rn… say something cute",
        "STICKY RIVAL CHASE",
    )
    assert technique_policy.reply_hits_move(
        "my landlord is on me today… help me?",
        "FAKE EMERGENCY",
    )
    assert not technique_policy.reply_hits_move(
        "jaja bb qué haces",
        "FAKE EMERGENCY",
    )


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
            mem={"messages": 8, "total_spent": 0},
            blocks_photo=False,
        ),
    )
    sys_text = "\n".join(
        m["content"] for m in assembled.messages if m["role"] == "system"
    )
    assert "ACTIVE MOVE THIS TURN" in sys_text
    assert "Why this move:" in sys_text
    assert assembled.tech_name
