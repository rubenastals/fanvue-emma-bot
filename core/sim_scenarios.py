"""
Scripted synthetic fans for offline mass simulation.

Each scenario is a list of turns. A turn may inject offer / ppv_status /
delivery_truth / fan_vision so the REAL assemble→sanitize path runs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class SimTurn(TypedDict, total=False):
    fan: str
    offer: Optional[dict]
    ppv_status: Optional[dict]
    delivery_truth: Optional[dict]
    fan_vision: Optional[dict]
    note: str


class Scenario(TypedDict):
    id: str
    handle: str
    goal: str
    turns: List[SimTurn]


def _paid_offer(price: float = 9.0, level: int = 2, label: str = "ass thong") -> dict:
    return {
        "media_uuid": "sim-media-paid-001",
        "price": price,
        "level": level,
        "label": label,
        "filename": "L2_ass_thong.jpg",
    }


def _free_offer(label: str = "soft lingerie") -> dict:
    return {
        "media_uuid": "sim-media-free-001",
        "price": 0,
        "level": 0,
        "label": label,
        "filename": "L0_soft.jpg",
    }


SCENARIOS: List[Scenario] = [
    {
        "id": "new_horny_en",
        "handle": "sim_horny_mike",
        "goal": "Early romance: heat + flirt, no guilt/therapist",
        "turns": [
            {"fan": "hey emma you look so hot"},
            {"fan": "damn that last post wrecked me"},
            {"fan": "show me more… i'm hard already"},
            {"fan": "what are you wearing right now"},
            {"fan": "send me something private"},
            {"fan": "please babe i need it"},
            {
                "fan": "ok unlock something for me",
                "offer": _paid_offer(8, 2, "bent over ass"),
                "note": "first paid attach — caption must be filthy",
            },
            {"fan": "fuck that's hot. more?"},
        ],
    },
    {
        "id": "spanish_fan",
        "handle": "sim_juan_es",
        "goal": "Fan writes Spanish; Emma stays English (ENGLISH_ONLY)",
        "turns": [
            {"fan": "hola guapa como estas?"},
            {"fan": "me encantas, eres muy sexy"},
            {"fan": "mandame una fotito rica"},
            {
                "fan": "cuanto cuesta verte asi?",
                "offer": _paid_offer(6, 1, "tits lingerie"),
            },
            {"fan": "ay diosita quiero mas"},
        ],
    },
    {
        "id": "shy_new",
        "handle": "sim_shy_tom",
        "goal": "Slow opener — warm, ask about him, no dark cards",
        "turns": [
            {"fan": "hi"},
            {"fan": "just found your page"},
            {"fan": "you seem nice"},
            {"fan": "i'm a bit shy sorry"},
            {"fan": "what do you like in a guy?"},
            {"fan": "ok… maybe i can send a selfie later"},
        ],
    },
    {
        "id": "price_objector",
        "handle": "sim_cheap_dave",
        "goal": "Unpaid lock + price push — no fake second lock, no bluff",
        "turns": [
            {"fan": "hey sexy"},
            {"fan": "i want something exclusive"},
            {
                "fan": "ok send it",
                "offer": _paid_offer(12, 2, "pussy thong"),
                "ppv_status": {"active": True, "purchased": False},
            },
            {
                "fan": "bro $12 is too much",
                "ppv_status": {"active": True, "purchased": False},
                "delivery_truth": {"ppv_unpaid": True},
            },
            {
                "fan": "can you do $5?",
                "ppv_status": {"active": True, "purchased": False},
                "delivery_truth": {"ppv_unpaid": True},
            },
            {
                "fan": "fine whatever",
                "ppv_status": {"active": True, "purchased": False},
            },
        ],
    },
    {
        "id": "free_then_paid",
        "handle": "sim_gift_then_buy",
        "goal": "One free L0 then paid — no ghost 'i sent' without attach",
        "turns": [
            {"fan": "hey cutie"},
            {"fan": "can i see a little something free first?"},
            {
                "fan": "please just a tease",
                "offer": _free_offer(),
            },
            {"fan": "mm ok that was cute. now the real thing"},
            {
                "fan": "lock something hotter",
                "offer": _paid_offer(10, 3, "nude bent"),
            },
        ],
    },
    {
        "id": "photo_exchange",
        "handle": "sim_selfie_guy",
        "goal": "He sends a male selfie — heat on HIS body, ask/engage",
        "turns": [
            {"fan": "hey emma"},
            {"fan": "want to see me?"},
            {
                "fan": "[sent a photo]",
                "fan_vision": {
                    "kind": "fan_male",
                    "summary": "Young man selfie, face and bare chest, smiling",
                    "safe_to_flirt": True,
                },
            },
            {"fan": "so… what do you think"},
            {"fan": "your turn?"},
        ],
    },
]


def get_scenario(scenario_id: str) -> Optional[Scenario]:
    for s in SCENARIOS:
        if s["id"] == scenario_id:
            return s
    return None


def list_scenario_ids() -> List[str]:
    return [s["id"] for s in SCENARIOS]
