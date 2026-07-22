"""Regression: Juan chat errors (quotes, left-photo bluff, grabar→candado)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from core import scheme_guard, technique_policy


def test_grabar_content_is_not_video_promise():
    # Creator workflow — must NOT trip invented-video fallback
    assert not scheme_guard.invented_video_claim(
        "Grabar contenido para mi página, cielo... ya sabes, fotitos"
    )
    assert not scheme_guard.invented_video_claim(
        "pero tengo que irme a grabar... pórtate bien"
    )
    # Real bad promise — still caught
    assert scheme_guard.invented_video_claim("te mando un vídeo custom bb")
    assert scheme_guard.invented_video_claim("i'll send you a video tonight")


def test_left_photo_claim_detected():
    assert scheme_guard.claims_left_photo(
        'y ni siquiera has abierto la foto que te dejé... así que no te quejes'
    )
    cleaned = scheme_guard.strip_left_photo_claims(
        'y ni siquiera has abierto la foto que te dejé... así que no te quejes, bebé'
    )
    assert "foto que te dej" not in cleaned.lower()
    assert "bebé" in cleaned or "bebe" in cleaned.lower() or "así" in cleaned


def test_fallback_no_lock_not_therapist():
    es = scheme_guard.fallback_no_lock(want_spanish=True)
    assert "Cuéntame qué te pasa" not in es
    assert "candada" not in es.lower()


def test_soft_clarify_avoids_emergency():
    from types import SimpleNamespace

    m = technique_policy.choose_move(
        "phase_pull",
        fan_uuid="juan-clarify",
        msgs=20,
        mem={
            "messages": 20,
            "total_spent": 0,
            "price_objection_step": 3,  # stale
        },
        fan_message="no me pasa nada. pq lo dices?",
        no_lock=True,
        ban_rival_fan=True,
        turn_action=SimpleNamespace(action="flirt"),
    )
    assert m is not None
    assert "EMERGENCY" not in m.name


def test_photos_only_fallback_not_robot_stamp():
    es = scheme_guard.fallback_photos_only(want_spanish=True, real_price=4.0)
    assert "UNA candada" not in es
    assert "Solo fotos 😏 Tienes" not in es
