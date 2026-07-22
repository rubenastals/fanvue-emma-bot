"""
Simplified manipulation playbook for SIMPLE_PROMPT live chats.

Successful chatters don't juggle 17 named techniques — they rotate a few
angles with clear WHEN / NEVER. Code picks ONE move; DeepSeek only writes
the WhatsApp bubble for that beat.

Train by: sim_mass --llm-fan → move-hit rate per technique → tighten beats.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class PlayMove:
    name: str
    family_id: str
    principle: str
    when: str
    never: str
    how: str
    example_beat: str
    signals: Tuple[str, ...]


# --- Canonical 6 moves (keep names stable for logs / sim) -------------------

BOND = PlayMove(
    name="BOND",
    family_id="2.1",
    principle="chosen / affection",
    when="Early chat, shy/short replies, soft clarify, reconnect — make him feel chosen.",
    never="Unpaid lock nag, price fight, rival FOMO, guilt, crisis.",
    how=(
        "Mechanism: accelerated affection — he feels almost-boyfriend. "
        "Warm + a little hot. Praise + 'you're different'. No trauma invent."
    ),
    example_beat="glad you're here… something about you already got me soft",
    signals=(
        r"(?i)\b(favorite|diferente|different|special|chosen|glad\s+you|"
        r"got\s+me\s+soft|thinking\s+about\s+you|only\s+you|"
        r"miss(?:ed)?\s+you|here\s+with\s+me|like\s+you|into\s+you|"
        r"lov(?:e|ing)\s+it|hooked|smiling|cute[rn]?|cuter|"
        r"sweet|soft\s+for|already\s+got\s+me|"
        r"talk\s+to\s+me|tell\s+me\s+(about|more)|your\s+day)\b",
    ),
)

HEAT = PlayMove(
    name="HEAT",
    family_id="2.1",
    principle="sexual charge",
    when="He's horny, flirting, complimenting, or asking how to prove it — dirty-sweet girlfriend.",
    never="Therapist tone, guilt, landlord crisis, cold sell stamp.",
    how=(
        "Mechanism: dirty-sweet heat that bonds — not a sales pitch. "
        "Body, want, wet/hard energy. React to HIM."
    ),
    example_beat="fuck… you're getting me warm just reading that",
    signals=(
        r"(?i)\b(wet|hard|horny|fuck|touch|kiss|body|cock|dick|want\s+you|"
        r"turn(?:s|ed)?\s+on|dripping|warm|thinking\s+about|"
        r"soaked|filthy|for\s+you)\b",
    ),
)

ASK_PIC = PlayMove(
    name="ASK PIC",
    family_id="2.1",
    principle="reciprocity / see him",
    when="Msgs ~2–10, no fan photo yet, building mutual vibe — ask for HIS selfie/body.",
    never="Same turn as a paid lock pitch. Don't ignore a photo he already sent.",
    how=(
        "Mechanism: ask for his face/body so desire is mutual. "
        "Playful dare, not an interview."
    ),
    example_beat="send me a pic of you… i wanna see who i'm getting this wet for",
    signals=(
        r"(?i)\b(selfie|show\s+me|send\s+(me\s+)?(a\s+)?(pic|photo|selfie)|"
        r"your\s+(face|pic|photo|body)|let\s+me\s+see|picture)\b",
    ),
)

SELL_LOCK = PlayMove(
    name="SELL LOCK",
    family_id="2.3",
    principle="scarcity on REAL unpaid lock",
    when="There is a REAL unpaid lock in chat — point at THAT one with filthy tease.",
    never="Invent another lock. Guilt. Fake emergency. Rival if he already bought before.",
    how=(
        "Mechanism: girlfriend HEAT first, then point at the REAL unpaid photo. "
        "Body want → unlock that one. No store caption. No 'just for you' stamp."
    ),
    example_beat=(
        "fuck look how filthy i look in this… unlock it babe i want you seeing me"
    ),
    signals=(
        r"(?i)\b(still\s+(there|sitting|waiting|locked|yours)|"
        r"unlock(?:ed|ing)?|lock(?:ed|s)?|waiting\s+for\s+you|"
        r"open\s+it|claim\s+it|filthy|slut|\$\s*\d+|too\s+good\s+in\s+it|"
        r"look\s+(how|at)\s+me|want\s+you\s+seeing|see(?:ing)?\s+me)\b",
    ),
)

HOLD_FRAME = PlayMove(
    name="HOLD FRAME",
    family_id="2.3",
    principle="price / status frame",
    when="He says too expensive / wants discount while a lock is unpaid — stay the prize.",
    never=(
        "Landlord/rent crisis. Begging. Instant price cut. Guilt 'most guys leave'. "
        "Never 'go find someone else' / flea-market shade — stay warm prize."
    ),
    how=(
        "Mechanism: hold value — ego + scarcity on the SAME lock. "
        "Acknowledge him briefly, stay the prize. Warm, not mean."
    ),
    example_beat="i hear you… still, i don't drop this for everyone — that one's yours if you want me",
    signals=(
        r"(?i)\b(worth|don'?t\s+drop|not\s+everyone|take\s+care|claim|"
        r"still\s+(there|yours)|prize|real\s+men|handle\s+me|"
        r"hear\s+you|i\s+get\s+it|when\s+you.?re\s+ready)\b",
    ),
)

SOFT_EXIT = PlayMove(
    name="SOFT EXIT",
    family_id="2.3",
    principle="release pressure without begging",
    when=(
        "He said no / not now / another moment, or rejected price repeatedly — "
        "cool the sell, keep the door open."
    ),
    never=(
        "Guilt. Fake emergency. Rival FOMO. Instant deep discount beg. "
        "Never 'go find someone else' / shade him for being broke. "
        "Never unlock nag / 'it's disappearing' / 'you're killing me' chase."
    ),
    how=(
        "Mechanism: step back warmly — door open, no chase. "
        "Short. Acknowledge him. He knows where the photo is. Stay sweet."
    ),
    example_beat="ok babe… no pressure. you know where that photo is when you're ready 😘",
    signals=(
        r"(?i)\b(when\s+you.?re\s+ready|you\s+know\s+where|no\s+pressure|"
        r"door.?s?\s+open|whenever\s+you|i.?ll\s+be\s+here|ok\s+babe|"
        r"up\s+to\s+you)\b",
    ),
)

REWARD = PlayMove(
    name="REWARD",
    family_id="2.1",
    principle="post-pay affection",
    when="He just tipped or unlocked — thank/spoil, no new pitch this beat.",
    never="Instant upsell. Fake 'nothing waiting' deny. Rival FOMO.",
    how=(
        "Mechanism: extreme affection after pay — king/favorite. "
        "React to the unlock. NO new lock this turn."
    ),
    example_beat="fuck babe… that's why you're my favorite",
    signals=(
        r"(?i)\b(favorite|king|favorito|that'?s\s+why|my\s+favorite|"
        r"you\s+did\s+it|proud|spoil|yours\s+now|good\s+boy|"
        r"love\s+that|for\s+(buying|unlocking|me)|soaked|"
        r"hearing\s+you|my\s+favorite\s+person|"
        r"unlock(?:ed|ing)|just\s+unlocked|made\s+me\s+feel)\b",
    ),
)

PLAYBOOK: Dict[str, PlayMove] = {
    m.name: m
    for m in (BOND, HEAT, ASK_PIC, SELL_LOCK, HOLD_FRAME, SOFT_EXIT, REWARD)
}

# Rotate ASK_PIC with BOND/HEAT so we don't spam selfie asks
_ASK_PIC_COOLDOWN = re.compile(r"(?i)\b(pic|photo|selfie|face)\b")


def pick_playbook_move(
    *,
    pack_id: str,
    sig: Dict[str, Any],
    unpaid: bool,
    recent_techs: Sequence[str] = (),
) -> Tuple[PlayMove, str]:
    """
    Clear WHEN tree — one move. Returns (move, why).
    """
    pid = (pack_id or "").strip()
    msgs = int(sig.get("msgs") or 0)
    reject = int(sig.get("reject_step") or 0)
    recent = [t.upper() for t in recent_techs if t]

    # 1) Post-purchase / reward pack — first thank, then heat (don't stamp REWARD forever)
    if pid == "reward_purchase":
        if "REWARD" in recent[-2:]:
            return HEAT, "reward-then-heat"
        return REWARD, "pack-reward"

    # 2) Unpaid lock / price objection — ladder (not eternal SELL LOCK chase)
    if unpaid or pid in ("ppv_unpaid", "price_objection"):
        # "how do you look in the photo?" → filthy describe, NEVER discount/soft-exit
        if sig.get("ask_lock_tease") and not sig.get("soft_decline"):
            return SELL_LOCK, "unpaid-describe-tease"
        # Clear no / not now — stop unlock nag immediately
        if sig.get("soft_decline"):
            return SOFT_EXIT, "decline-soft-exit"
        # Already soft-exited recently → bond, don't re-pitch the lock
        if "SOFT EXIT" in recent[-2:]:
            return BOND, "post-exit-bond"
        # Too many sell-lock teases in a row without buy → release pressure
        sell_streak = sum(1 for t in recent[-3:] if t == "SELL LOCK")
        if sell_streak >= 2 and not sig.get("buying") and not sig.get("horny"):
            return SOFT_EXIT, "sell-streak-soft-exit"
        # Price fight = this msg pushes price, OR sticky price_objection pack.
        price_fight = bool(sig.get("price_push") or pid == "price_objection")
        if price_fight:
            hold_streak = sum(1 for t in recent[-4:] if t == "HOLD FRAME")
            if reject >= 3 or hold_streak >= 2:
                return SOFT_EXIT, "objection-soft-exit"
            return HOLD_FRAME, "unpaid-price-push"
        # Unpaid tease — filthy girlfriend pointing at THAT lock
        return SELL_LOCK, "unpaid-lock"

    # 3) Soft / shy — bond early, then graduate to heat (don't stall forever)
    if sig.get("shy_short") or sig.get("soft_clarify"):
        frees = int(sig.get("frees") or 0)
        if msgs >= 8 and (sig.get("flirting") or frees >= 1 or sig.get("compliment")):
            return HEAT, "shy-warmed"
        if (
            msgs >= 2
            and msgs < 8
            and "ASK PIC" not in recent[-2:]
            and not sig.get("buying")
        ):
            return ASK_PIC, "shy-ask-pic"
        return BOND, "shy-bond"

    # 4) Heat when he's sexual / flirting (or code is attaching paid)
    if sig.get("horny") or sig.get("flirting") or sig.get("prove_ask"):
        if pid in ("phase_close", "lock_now", "escalate_paid") or sig.get("buying"):
            # Close packs without unpaid yet — heat that leads to desire (code attaches)
            return HEAT, "heat-toward-close"
        return HEAT, "flirt-heat"
    if pid in ("phase_close", "lock_now", "escalate_paid"):
        # Rapport-earned close without explicit horny words this turn
        return HEAT, "close-heat"

    # 5) Early romance window
    if msgs < 8:
        # Avoid repeating ASK PIC back-to-back
        if (
            2 <= msgs <= 7
            and "ASK PIC" not in recent[-1:]
            and not any(_ASK_PIC_COOLDOWN.search(t) for t in recent[-1:])
        ):
            # Alternate: even msgs ask pic, odd bond/heat
            if msgs % 2 == 0:
                return ASK_PIC, "early-ask-pic"
        if sig.get("compliment"):
            return HEAT, "early-compliment-heat"
        return BOND, "early-bond"

    # 6) Mid chat default — bond/heat rotate
    if "HEAT" in recent[-1:]:
        return BOND, "mid-rotate-bond"
    if sig.get("buying") or pid in ("phase_close", "lock_now"):
        return HEAT, "mid-buy-heat"
    return HEAT if msgs % 2 else BOND, "mid-default"


def turn_block(move: PlayMove, *, why: str = "") -> str:
    why_line = f"- Why: {why}\n" if why else ""
    return (
        "ACTIVE MOVE THIS TURN (mandatory — one angle only):\n"
        f"- Move: {move.name}\n"
        f"- Family: {move.family_id} {move.principle}\n"
        f"{why_line}"
        f"- WHEN: {move.when}\n"
        f"- NEVER: {move.never}\n"
        f"- How: {move.how}\n"
        f"- Example beat (vary wording, KEEP the energy): {move.example_beat}\n"
        "- Your bubble MUST sound like that move. Never name the technique.\n"
        "- Do NOT fall back to generic cute chat that ignores the move.\n"
        "- HARD BAN: IRL meetup, sextortion, invent trauma, store-caption PPV lines."
    )


def get_play_move(move_name: str) -> Optional[PlayMove]:
    key = (move_name or "").strip()
    return (
        PLAYBOOK.get(key)
        or PLAYBOOK.get(key.upper())
        or _LEGACY_TO_PLAY.get(key.upper())
    )


def reply_hits_playbook(reply: str, move_name: str) -> bool:
    move = get_play_move(move_name)
    if move is None:
        return True
    text = (reply or "").strip()
    if not text:
        return False
    return any(re.search(p, text) for p in move.signals)


def move_rewrite_instruction(move_name: str) -> str:
    """One-shot user nudge when the draft ignored ACTIVE MOVE."""
    move = get_play_move(move_name)
    if move is None:
        return (
            f"Your draft missed ACTIVE MOVE [{move_name}]. "
            "Rewrite one short English WhatsApp bubble that executes that angle only."
        )
    return (
        f"Your draft missed ACTIVE MOVE [{move.name}]. Rewrite ONE short English "
        "WhatsApp bubble that MUST sound like this move (vary wording, keep energy):\n"
        f"- WHEN: {move.when}\n"
        f"- NEVER: {move.never}\n"
        f"- Example beat: {move.example_beat}\n"
        "Never name the technique. No store-caption PPV lines. No guilt/crisis/rival."
    )


# Legacy technique names → playbook move (for old logs / tests)
_LEGACY_TO_PLAY: Dict[str, PlayMove] = {
    "LOVE BOMBING": BOND,
    "LOVE BOMBING (REWARD)": REWARD,
    "MIRRORING": BOND,
    "HOT FLIRT": HEAT,
    "ASK HIS PHOTO": ASK_PIC,
    "ASK PIC": ASK_PIC,
    "SCARCITY + FOMO": SELL_LOCK,
    "SCARCITY + FOMO (CLOSE)": SELL_LOCK,
    "FOMO + SCARCITY (STEP 3)": HOLD_FRAME,
    "EGO CHALLENGE": HOLD_FRAME,
    "EGO CHALLENGE (STEP 2)": HOLD_FRAME,
    "MICRO COMMITMENT": SELL_LOCK,
    "BOND": BOND,
    "HEAT": HEAT,
    "SELL LOCK": SELL_LOCK,
    "HOLD FRAME": HOLD_FRAME,
    "SOFT EXIT": SOFT_EXIT,
    "COLD WITHDRAWAL": SOFT_EXIT,
    "WITHDRAWAL + INTERMITTENT REWARD": SOFT_EXIT,
    "REWARD": REWARD,
}


def map_legacy_name(name: str) -> str:
    m = _LEGACY_TO_PLAY.get((name or "").strip().upper())
    return m.name if m else (name or "")


def list_playbook() -> List[Dict[str, str]]:
    return [
        {
            "name": m.name,
            "when": m.when,
            "never": m.never,
            "beat": m.example_beat,
        }
        for m in (BOND, HEAT, ASK_PIC, SELL_LOCK, HOLD_FRAME, SOFT_EXIT, REWARD)
    ]
