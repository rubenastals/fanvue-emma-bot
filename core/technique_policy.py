"""
Live per-turn psychology move (SIMPLE path).

Strategy = CODE picks the move from fan state + pack + ACTION.
Creativity = DeepSeek writes WhatsApp text for that move.
Compliance = soft signal check after draft (log / SCHEME), not another essay.

Under SIMPLE_PROMPT=1: uses the slim 6-move playbook
(`core/technique_playbook.py`) with a clear WHEN tree — not 17 scored techs.

How-tos / instructions: English only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import config
from core import manipulation
from core import technique_playbook as playbook
from core.fan_pushback import (
    fan_has_pushback,
    is_ai_complaint,
    is_flattery_skeptic,
    is_vision_correction,
)
from core.soft_decline import is_soft_decline

# First N messages: romance / heat / ask-his-photo only — dark cards later.
EARLY_ROMANCE_MAX_MSGS = 8
_EARLY_SAFE = frozenset(
    {
        "LOVE BOMBING",
        "HOT FLIRT",
        "ASK HIS PHOTO",
        "MIRRORING",
        "FUTURE FAKING (light)",
        "FUTURE FAKING",
        "MICRO COMMITMENT",
        "LOVE BOMBING (REWARD)",
    }
)
_EARLY_DARK = frozenset(
    {
        "GUILT",
        "EMERGENCY",
        "RIVAL",
        "EGO CHALLENGE",
        "LOYALTY PROVE",
        "WITHDRAWAL",
        "SCARCITY",
        "FOMO",
        "GASLIGHTING",
        "PAIN MAP",
    }
)


@dataclass(frozen=True)
class ActiveMove:
    name: str
    how: str
    why: str = ""
    family_id: str = ""
    principle: str = ""


# Soft compliance: reply should hit at least one signal for the assigned move.
# Not a rewrite hammer — flags generic filler that ignored ACTIVE MOVE.
_MOVE_SIGNALS: Dict[str, Tuple[str, ...]] = {
    "LOVE BOMBING": (
        r"(?i)\b(favorite|diferente|different|special|chosen|único|unico|"
        r"only\s+you|solo\s+t[uú]|thinking\s+about\s+you|pensando\s+en\s+ti|"
        r"soft|glad\s+you|got\s+me)\b",
    ),
    "LOVE BOMBING (REWARD)": (
        r"(?i)\b(favorite|king|favorito|así\s+sí|thats?\s+why|my\s+favorite)\b",
    ),
    "HOT FLIRT": (
        r"(?i)\b(wet|hard|horny|fuck|touch|kiss|body|cock|dick|want\s+you|"
        r"turn(?:s|ed)?\s+on|dripping|thinking\s+about)\b",
    ),
    "ASK HIS PHOTO": (
        r"(?i)\b(selfie|show\s+me|send\s+(me\s+)?(a\s+)?(pic|photo|selfie)|"
        r"your\s+(face|pic|photo|body)|let\s+me\s+see|picture)\b",
    ),
    "MIRRORING": (
        r"(?i)\b(same|igual|yo\s+también|me\s+too|tell\s+me|cuéntame|cuentame)\b",
    ),
    "FUTURE FAKING": (
        r"(?i)\b(every\s+day|cada\s+d[ií]a|favorite|favorito|with\s+me|"
        r"contigo|imagine|imagínate|imaginate)\b",
    ),
    "FUTURE FAKING (light)": (
        r"(?i)\b(every\s+night|cada\s+noche|imagine|imagínate|with\s+me|contigo)\b",
    ),
    "INTERMITTENT REINFORCEMENT": (
        r"(?i)\b(maybe|tal\s+vez|if\s+you|si\s+te|behave|portas|later|dps|después)\b",
    ),
    "LOVE BOMBING + WITHDRAWAL": (
        r"(?i)\b(gotta\s+go|me\s+voy|busy|grabar|shoot|later|dps|don't\s+leave|"
        r"no\s+me\s+dejes)\b",
    ),
    "WITHDRAWAL + INTERMITTENT REWARD": (
        r"(?i)\b(stepping\s+away|me\s+voy|later|dps|if\s+you.?re\s+lucky|si\s+tienes\s+suerte)\b",
    ),
    "EGO CHALLENGE": (
        r"(?i)\b(prove|demuestra|just\s+talk|solo\s+hablas|claim|reclama|"
        r"real\s+man|hombre|different|distinto)\b",
    ),
    "EGO CHALLENGE (Step 2)": (
        r"(?i)\b(prove|demuestra|take\s+care|cuid|just\s+talk|solo\s+hablas)\b",
    ),
    "LOYALTY PROVE": (
        r"(?i)\b(matter|import|show\s+me|demuéstr|demuestr|loyalty|leal|"
        r"not\s+just\s+an?\s+object|objeto)\b",
    ),
    "RIVAL TIP FOMO": (
        r"(?i)\b(tip|propina|\$\d+|another\s+(guy|fan)|otro|someone\s+just|"
        r"snatch|quise|offered)\b",
    ),
    "WRONG MESSAGE JEALOUSY": (
        r"(?i)\b(wrong\s+chat|chat\s+equivocado|thanks\s+for\s+the|"
        r"gracias\s+por\s+(los\s+)?\d+|peter|wait\s+wrong)\b",
    ),
    "RIVAL VIDEOCALL BAIT": (
        r"(?i)\b(call|videollamada|private\s+call|offered|ofreció|ofrecio|"
        r"another\s+(guy|fan)|otro)\b",
    ),
    "STICKY RIVAL CHASE": (
        r"(?i)\b(another\s+(guy|fan)|otro\s+(fan|chico|tipo)|texting\s+me|"
        r"me\s+escribe|say\s+something\s+cute|dime\s+algo|before\s+i\s+answer|"
        r"antes\s+de\s+que\s+(le\s+)?responda)\b",
    ),
    "SCARCITY + FOMO": (
        r"(?i)\b(waiting|esperando|won't\s+sit|no\s+se\s+queda|forever|"
        r"arriba|still\s+there|desaparec|unlock|desbloque|candado)\b",
    ),
    "SCARCITY + FOMO (CLOSE)": (
        r"(?i)\b(for\s+you|pa\s+ti|para\s+ti|not\s+leaving|no\s+lo\s+dejo|"
        r"claim|reclama|just\s+yours|solo\s+tuyo)\b",
    ),
    "FOMO + SCARCITY (Step 3)": (
        r"(?i)\b(forever|offered|ofre|won't\s+sit|no\s+se\s+queda|another|"
        r"otro|miss)\b",
    ),
    "GUILT TRIP + RECIPROCITY": (
        r"(?i)\b(opened\s+up|abr[ií]|taste|gusto|show\s+me|demuéstr|"
        r"hurt|duele|left\s+it|dejaste|after\s+everything|después\s+de|"
        r"don'?t\s+just\s+take|no\s+solo\s+tomar)\b",
    ),
    "GUILT TRIP + SCARCITY": (
        r"(?i)\b(taste|gusto|gratis|free|now\s+something|ahora\s+toca|real)\b",
    ),
    "GUILT TRIP (Step 1)": (
        r"(?i)\b(expensive|caro|for\s+you|para\s+ti|made\s+it|hice)\b",
    ),
    "FAKE EMERGENCY": (
        r"(?i)\b(landlord|casero|alquiler|rent|medical|m[eé]dic|debt|deuda|"
        r"kicked\s+out|help\s+me|ayúdame|ayudame|screwed|hoy|tonight|"
        r"rough\s+day|necesito)\b",
    ),
    "MICRO COMMITMENT": (
        r"(?i)\b(tell\s+me|dime|want\s+it|lo\s+quieres|trust\s+me|confías|"
        r"confias|yes\s+or|sí\s+o\s+sí|si\s+o\s+si)\b",
    ),
    "GASLIGHTING (soft)": (
        r"(?i)\b(overthinking|rayando|not\s+ready|no\s+est[aá]s\s+list|"
        r"maybe\s+you|a\s+lo\s+mejor)\b",
    ),
    "PAIN MAP VALIDATE": (
        r"(?i)\b(hard|duro|alone|solo|understand|entiendo|with\s+you|"
        r"contigo|here\s+for\s+you|aquí\s+estoy|aqui\s+estoy)\b",
    ),
    "COLD WITHDRAWAL (Step 4)": (
        r"(?i)\b(alright|bueno|you\s+know\s+where|sabes\s+dónde|sabes\s+donde|"
        r"i.?m\s+here|aquí\s+estoy)\b",
    ),
    "LOVE BOMBING + GUILT + FOMO": (
        r"(?i)\b(almost|casi|miss|pensé|pense|still\s+there|seguís|seguis|there)\b",
    ),
}


def effective_pack_for_move(
    pack_id: str,
    *,
    turn_action: Any = None,
    unpaid: bool = False,
    cooling: bool = False,
    soft_support: bool = False,
    soft_unpaid: bool = False,
) -> str:
    """Map this turn's situation → technique catalog pack. Empty = skip."""
    if cooling or soft_support or soft_unpaid:
        return ""
    action = getattr(turn_action, "action", None) if turn_action is not None else None
    if action == "comfort":
        return ""
    if action == "send_voice":
        return "phase_hook"
    if pack_id == "price_objection":
        return "price_objection"
    if unpaid or pack_id == "ppv_unpaid":
        return "ppv_unpaid"
    if action == "attach_ppv":
        if pack_id in ("phase_close", "lock_now", "escalate_paid"):
            return pack_id
        return "phase_close"
    if action == "attach_free":
        return "ask_free_first" if pack_id == "ask_free_first" else "phase_hook"
    if pack_id in manipulation._TECH_BY_PACK:
        return pack_id
    return "phase_pull"


def _recent_families(exclude_names: Optional[Sequence[str]]) -> List[str]:
    out: List[str] = []
    for n in exclude_names or []:
        fam, _ = manipulation.family_for(str(n))
        if fam:
            out.append(fam)
    return out


def _fan_signals(mem: Optional[dict], fan_message: str) -> Dict[str, Any]:
    mem = mem or {}
    low = (fan_message or "").lower()
    spent = float(mem.get("total_spent") or mem.get("spent") or 0)
    purchases = int(mem.get("purchases") or 0)
    msgs = int(mem.get("messages") or 0)
    frees = int(mem.get("free_teases_sent") or mem.get("frees_done") or 0)
    reject_step = int(mem.get("price_objection_step") or 0)
    status = (mem.get("status") or "").lower()
    cardish = bool(
        mem.get("name")
        or mem.get("notes")
        or mem.get("likes")
        or mem.get("card_facts")
    )
    buying = bool(
        re.search(
            r"(?i)\b(buy|compr|unlock|desbloque|tip|propina|send\s+it|mánda|manda)\b",
            low,
        )
    )
    price_push = bool(
        re.search(
            r"(?i)\b(caro|expensive|too\s+much|descuento|discount|barato)\b",
            low,
        )
    )
    # Soft "not now" / clear no — stop unlock chase (not the same as haggling)
    soft_decline = is_soft_decline(low)
    # Asking what's IN the unpaid lock — tease/describe, not price fight
    ask_lock_tease = bool(
        re.search(
            r"(?i)\b("
            r"how\s+do\s+you\s+look|what\s+do\s+you\s+look\s+like|"
            r"how\s+do\s+u\s+look|how\s+are\s+you\s+(looking|posed)|"
            r"what.?s\s+in\s+(the|that)\s+(photo|pic|lock)|"
            r"what\s+(is|does)\s+(the|that)\s+(photo|pic)|"
            r"what\s+are\s+you\s+wearing|describe\s+(the|that|your)\s+(photo|pic|lock)|"
            r"c[oó]mo\s+(est[aá]s|sales|te\s+ves)|qu[eé]\s+se\s+ve|"
            r"qu[eé]\s+hay\s+en\s+(la|esa)\s+foto|c[oó]mo\s+est[aá]s\s+en\s+(la|esa)"
            r")\b",
            low,
        )
    )
    horny = bool(
        re.search(
            r"(?i)\b(hard|horny|cock|dick|pussy|fuck|cum|mojad|caliente|polla)\b",
            low,
        )
    )
    compliment = bool(
        re.search(
            r"(?i)\b("
            r"pretty|beautiful|sexy|hot|gorgeous|stunning|cute|handsome|"
            r"guapa|guapo|preciosa|bonita|rica|hermosa|linda|"
            r"look\s+amazing|lok\s+super|you'?re\s+(so\s+)?(hot|sexy|pretty)"
            r")\b",
            low,
        )
    )
    prove_ask = bool(
        re.search(
            r"(?i)\b(prove|demuestr|how\s+can\s+i\s+prove|what\s+do\s+you\s+want\s+me\s+to\s+do)\b",
            low,
        )
    )
    # Real emotional vent — only then PAIN MAP is OK
    venting = bool(
        re.search(
            r"(?i)\b("
            r"depressed|anxiety|lonely|divorce|broke|fired|died|funeral|"
            r"suicid|hurt\s+inside|crying|cry\b|my\s+(ex|wife|mom)|"
            r"depressed|triste|solo|sola|ansiedad|lloro|divorci"
            r")\b",
            low,
        )
    )
    flirting = bool(horny or compliment or prove_ask)
    # Soft clarify / follow-up — not a crisis beat
    soft_clarify = bool(
        re.search(
            r"(?i)^\s*("
            r"pq\b|por\s*qu[eé]|why\b|c[oó]mo\b|como\b|a\s+grabar|"
            r"qu[eé]\s+dices|what\s+do\s+you\s+mean|no\s+me\s+pasa|"
            r"nada\b|ok\b|ahh+|jaj+|ahah"
            r")",
            low,
        )
    ) or (len(low) <= 28 and low.endswith("?") and not prove_ask)
    # Shy / low-effort: short dry texts — never guilt/crisis/rival.
    # Age out after rapport so we can heat / soft-close (was stalling shy sims).
    shy_short = bool(
        len(low) <= 40
        and not buying
        and not horny
        and not price_push
        and not venting
        and msgs < 8
        and frees < 1
    )
    fan_sent_photo = bool(mem.get("last_fan_image_desc"))
    if mem.get("last_fan_image_at"):
        try:
            from datetime import datetime, timedelta, timezone

            ts = datetime.fromisoformat(
                str(mem["last_fan_image_at"]).replace("Z", "+00:00")
            )
            fan_sent_photo = datetime.now(timezone.utc) - ts < timedelta(hours=72)
        except Exception:
            fan_sent_photo = bool(mem.get("last_fan_image_desc"))
    fan_pushback = fan_has_pushback(low)
    return {
        "spent": spent,
        "purchases": purchases,
        "msgs": msgs,
        "frees": frees,
        "reject_step": reject_step,
        "status": status,
        "cardish": cardish,
        "buying": buying,
        "price_push": price_push,
        "soft_decline": soft_decline,
        "ask_lock_tease": ask_lock_tease,
        "horny": horny,
        "compliment": compliment,
        "prove_ask": prove_ask,
        "venting": venting,
        "flirting": flirting,
        "soft_clarify": soft_clarify,
        "shy_short": shy_short,
        "zero_spender": spent <= 0 and purchases <= 0,
        "fan_sent_photo": fan_sent_photo,
        "fan_pushback": fan_pushback,
        "ai_complaint": is_ai_complaint(low),
        "flattery_skeptic": is_flattery_skeptic(low),
        "vision_correction": is_vision_correction(low),
    }


def score_move(
    name: str,
    *,
    eff_pack: str,
    sig: Dict[str, Any],
    recent_fams: Sequence[str],
    turn_action: Any = None,
    unpaid: bool = False,
    no_lock: bool = False,
) -> Tuple[int, str]:
    """Return (score, why). Higher = better fit for this fan/turn."""
    action = getattr(turn_action, "action", None) if turn_action is not None else None
    fam, _ = manipulation.family_for(name)
    up = name.upper()
    score = 10
    why: List[str] = ["base"]

    # Diversify families across turns
    if fam and fam in recent_fams[-2:]:
        score -= 8
        why.append(f"penalize-repeat-family-{fam}")
    elif fam and fam in recent_fams:
        score -= 3
        why.append("soft-penalize-family")

    objection_live = bool(
        sig["price_push"]
        or eff_pack == "price_objection"
        or (sig["reject_step"] > 0 and not sig.get("soft_clarify"))
    )
    early = (
        int(sig.get("msgs") or 0) < EARLY_ROMANCE_MAX_MSGS
        and not unpaid
        and not objection_live
        and eff_pack
        not in ("ppv_unpaid", "price_objection", "phase_close", "lock_now", "escalate_paid")
    )

    # Early romance window → love / heat / ask his photo. Dark cards scare him off.
    if early:
        if name in _EARLY_SAFE or any(k in up for k in ("LOVE BOMBING", "MIRRORING", "HOT FLIRT", "ASK HIS PHOTO", "FUTURE FAKING")):
            score += 14
            why.append("early-romance")
        if up == "ASK HIS PHOTO":
            score += 4
            why.append("early-ask-photo")
        if up == "HOT FLIRT" and (sig.get("horny") or sig["msgs"] >= 3):
            score += 4
            why.append("early-heat")
        if any(d in up for d in _EARLY_DARK) or name in manipulation._RIVAL_TECHS:
            score -= 30
            why.append("too-early-for-dark")

    # Mid-chat bond still prefers intimacy before pressure (msgs 8–14)
    elif sig["msgs"] < 14 and not unpaid and not objection_live:
        if "LOVE BOMBING" in up or up in ("MIRRORING", "HOT FLIRT", "ASK HIS PHOTO"):
            score += 6
            why.append("still-bond")
        if "EMERGENCY" in up or name in manipulation._RIVAL_TECHS:
            score -= 8
            why.append("still-early-pressure")

    # Zero spender mid-chat → commitment / intermittent (NOT abandonment-guilt)
    if sig["zero_spender"] and sig["msgs"] >= EARLY_ROMANCE_MAX_MSGS:
        if "MICRO COMMITMENT" in up or "INTERMITTENT" in up:
            score += 8
            why.append("zero-spender-hook")
        # After a free tease: heat + ask his pic when he's flirting; else soft commit
        if sig["frees"] >= 1:
            if sig.get("flirting"):
                if up in ("HOT FLIRT", "ASK HIS PHOTO") or "LOVE BOMBING" in up:
                    score += 8
                    why.append("free-then-heat")
            elif "LOYALTY" in up or "MICRO COMMITMENT" in up:
                score += 6
                why.append("free-given-reciprocity")

    # Heat / buy intent → close pressure (not in early romance window)
    if (sig["buying"] or sig["horny"] or action == "attach_ppv") and not early:
        if "SCARCITY" in up or "FOMO" in up or "EGO" in up or "CLOSE" in up:
            score += 10
            why.append("heat-close")
        if "EMERGENCY" in up and not sig["price_push"]:
            score -= 4
            why.append("heat-not-crisis")

    # Unpaid lock → hold frame (scarcity/heat). Guilt/crisis removed from catalog;
    # still hard-penalize if they leak from elsewhere.
    if unpaid or eff_pack == "ppv_unpaid":
        if "SCARCITY" in up or ("FOMO" in up and "RIVAL" not in up):
            score += 12
            why.append("unpaid-hold-frame")
        if up in ("HOT FLIRT", "MICRO COMMITMENT"):
            score += 8
            why.append("unpaid-heat-hold")
        if "RIVAL" in up:
            if sig["reject_step"] >= 2 and not sig.get("shy_short") and sig["purchases"] <= 0:
                score += 4
                why.append("unpaid-rival-late")
            else:
                score -= 16
                why.append("unpaid-rival-banned")
        if "GUILT" in up:
            score -= 22
            why.append("unpaid-guilt-banned")
        if "EMERGENCY" in up:
            score -= 22
            why.append("unpaid-crisis-banned")

    # Price pushback → hold frame / ego; never crisis; rival only late
    if objection_live:
        if "EGO" in up or ("FOMO" in up and "EMERGENCY" not in up) or "SCARCITY" in up:
            score += 10
            why.append("objection-hold-frame")
        if "GUILT" in up or "EMERGENCY" in up:
            score -= 20
            why.append("objection-guilt-crisis-banned")
        if "RIVAL" in up and sig["reject_step"] < 2:
            score -= 12
            why.append("objection-rival-too-soon")
        if "WITHDRAWAL" in up and sig["reject_step"] >= 3:
            score += 10
            why.append("objection-exit")

    # HARD: guilt never mid-chat while he's writing; never on shy/short
    if "GUILT" in up:
        if not unpaid and not objection_live:
            score -= 25
            why.append("ban-midchat-abandonment-guilt")
        if sig.get("shy_short") or sig.get("soft_clarify"):
            score -= 20
            why.append("ban-guilt-on-shy")

    # Soft clarify / shy short → bond/mirror/heat, not crisis/rival/guilt
    if sig.get("soft_clarify") or sig.get("shy_short"):
        if "EMERGENCY" in up or "GUILT" in up or name in manipulation._RIVAL_TECHS:
            score -= 18
            why.append("shy-not-dark")
        if up in ("MIRRORING", "HOT FLIRT", "ASK HIS PHOTO") or "LOVE BOMBING" in up:
            score += 8
            why.append("shy-soft-heat")

    # Reward pack
    if eff_pack == "reward_purchase":
        if "REWARD" in up or "LOVE BOMBING" in up:
            score += 15
            why.append("reward")
        else:
            score -= 20
            why.append("not-reward")

    # Pain map ONLY when he's actually venting — never mid-flirt
    # (live bug: PAIN MAP → "nice having someone give a damn" therapist loop)
    if "PAIN MAP" in up:
        if sig.get("venting") and sig["cardish"] and sig["msgs"] >= 6:
            score += 10
            why.append("real-vent-pain")
        else:
            score -= 20
            why.append("pain-map-not-flirting")

    # He's flirting / complimenting / asking how to prove → HEAT, not soft therapy
    if sig.get("flirting"):
        if up in ("HOT FLIRT", "ASK HIS PHOTO") or "LOVE BOMBING" in up:
            score += 12
            why.append("flirt-heat")
        if up == "HOT FLIRT":
            score += 4
            why.append("hot-flirt-priority")
        if sig.get("prove_ask") and (
            up == "HOT FLIRT" or "MICRO COMMITMENT" in up or up == "ASK HIS PHOTO"
        ):
            score += 8
            why.append("prove-with-heat")
        if "LOYALTY" in up and not sig.get("prove_ask"):
            score -= 10
            why.append("loyalty-not-during-compliment")
        if "PAIN MAP" in up or "GASLIGHTING" in up:
            score -= 15
            why.append("no-therapy-during-flirt")

    # Rival: never after he already paid (breaks "chosen" fantasy); rare otherwise
    if name in manipulation._RIVAL_TECHS:
        if sig["purchases"] > 0 or sig["spent"] > 0:
            score -= 20
            why.append("rival-after-purchase-banned")
        elif sig["msgs"] >= 10 and sig["reject_step"] >= 2 and sig["zero_spender"]:
            score += 5
            why.append("rival-fit-stalled-zero")
        if sig["msgs"] < 8 or sig.get("shy_short"):
            score -= 12
            why.append("rival-early")

    # Fake emergency: effectively banned (catalog removed); keep hammer if leaked
    if "EMERGENCY" in up:
        score -= 20
        why.append("crisis-banned")

    # No lock → don't prefer lock-scarcity names (filter usually drops them)
    if no_lock and "SCARCITY + FOMO" in up and "RIVAL" not in up:
        score -= 15
        why.append("no-lock")

    # Attach free → love bomb / mirror
    if action == "attach_free":
        if "LOVE BOMBING" in up or up == "MIRRORING":
            score += 10
            why.append("free-gift-warmth")

    return score, "+".join(why[:5])


def choose_move(
    pack_id: str,
    *,
    fan_uuid: str = "",
    msgs: int = 0,
    reject_count: int = 0,
    no_lock: bool = False,
    soft_support: bool = False,
    ban_withdrawal: bool = False,
    ban_rival_fan: bool = False,
    exclude_names: Optional[List[str]] = None,
    turn_action: Any = None,
    unpaid: bool = False,
    cooling: bool = False,
    soft_unpaid: bool = False,
    mem: Optional[dict] = None,
    fan_message: str = "",
) -> Optional[ActiveMove]:
    """
    Pick ONE move strategically from fan state + pack.

    SIMPLE_PROMPT=1 → slim playbook WHEN tree (6 moves).
    Legacy SIMPLE=0 → old scored catalog (kept for tests / rollback).
    """
    eff = effective_pack_for_move(
        pack_id or "",
        turn_action=turn_action,
        unpaid=unpaid,
        cooling=cooling,
        soft_support=soft_support,
        soft_unpaid=soft_unpaid,
    )
    if not eff:
        return None

    # --- Slim playbook (live default) ---------------------------------
    if getattr(config, "SIMPLE_PROMPT", True):
        if eff == "ask_free_first":
            eff = "phase_hook"
        sig = _fan_signals(mem, fan_message)
        if mem is not None and int(mem.get("messages") or 0):
            sig["msgs"] = int(mem.get("messages") or msgs or 0)
        elif msgs:
            sig["msgs"] = msgs
        from core import fan_memory as _fm

        sig["sell_paused"] = _fm.sell_pressure_paused(
            mem, recent_techniques=list(exclude_names or [])
        )
        # Sync reject ladder into signals
        if reject_count:
            sig["reject_step"] = max(int(sig.get("reject_step") or 0), int(reject_count))
        recent = list(exclude_names or [])
        move, why = playbook.pick_playbook_move(
            pack_id=eff,
            sig=sig,
            unpaid=unpaid or eff == "ppv_unpaid",
            recent_techs=recent,
        )
        print(f"   move: playbook [{move.name}] why={why} (pack={eff})")
        return ActiveMove(
            name=move.name,
            how=f"{move.how} Beat: {move.example_beat}",
            why=why,
            family_id=move.family_id,
            principle=move.principle,
        )

    # --- Legacy fat catalog path --------------------------------------
    if eff not in manipulation._TECH_BY_PACK:
        if eff == "ask_free_first":
            eff = "phase_hook"
        else:
            return None

    force_no_lock = bool(no_lock) and eff not in (
        "ppv_unpaid",
        "phase_close",
        "lock_now",
        "escalate_paid",
    )

    # Objection ladder stays sequential (strategic script)
    if eff == "price_objection":
        picked = manipulation.pick_technique(
            eff,
            fan_uuid=fan_uuid or "",
            msgs=msgs,
            reject_count=reject_count,
            no_lock=force_no_lock,
            soft_support=soft_support,
            exclude_names=exclude_names,
            ban_withdrawal=ban_withdrawal,
            ban_rival_fan=ban_rival_fan,
        )
        if not picked:
            return None
        name, how = picked
        fam, principle = manipulation.family_for(name)
        return ActiveMove(
            name=name,
            how=how,
            why=f"objection-step-{int(reject_count)}",
            family_id=fam,
            principle=principle,
        )

    sig = _fan_signals(mem, fan_message)
    # Prefer live mem message count when present
    if mem is not None and int(mem.get("messages") or 0):
        sig["msgs"] = int(mem.get("messages") or msgs or 0)
    elif msgs:
        sig["msgs"] = msgs

    # After he paid / shy short → never rival FOMO
    if int(sig.get("purchases") or 0) > 0 or float(sig.get("spent") or 0) > 0:
        ban_rival_fan = True
    if sig.get("shy_short") or sig.get("soft_clarify"):
        ban_rival_fan = True

    catalog = manipulation._filter_catalog(
        list(manipulation._TECH_BY_PACK.get(eff) or []),
        no_lock=force_no_lock,
        soft_support=soft_support,
        ban_rival_fan=ban_rival_fan,
    )
    exclude_u = {n.strip().upper() for n in (exclude_names or []) if n and n.strip()}
    if ban_withdrawal:
        exclude_u.add("LOVE BOMBING + WITHDRAWAL")
    # Structural ban: guilt + fake emergency never chosen from live catalogs
    for banned in (
        "GUILT TRIP + RECIPROCITY",
        "GUILT TRIP + SCARCITY",
        "GUILT TRIP (STEP 1)",
        "FAKE EMERGENCY",
        "LOVE BOMBING + GUILT + FOMO",
    ):
        exclude_u.add(banned)
    pool = [(n, h) for n, h in catalog if n.upper() not in exclude_u] or list(catalog)
    if not pool:
        return None

    # Early romance: force the warm/hot catalog (not phase_pull guilt/rival).
    early_romance = (
        int(sig.get("msgs") or 0) < EARLY_ROMANCE_MAX_MSGS
        and not unpaid
        and eff
        not in (
            "price_objection",
            "ppv_unpaid",
            "phase_close",
            "lock_now",
            "escalate_paid",
        )
    )
    if early_romance and eff != "phase_hook":
        eff = "phase_hook"
        catalog = manipulation._filter_catalog(
            list(manipulation._TECH_BY_PACK.get(eff) or []),
            no_lock=force_no_lock,
            soft_support=soft_support,
            ban_rival_fan=True,  # never rival in early romance
        )
        pool = [(n, h) for n, h in catalog if n.upper() not in exclude_u] or list(
            catalog
        )
        if not pool:
            return None
        print(
            f"   move: early-romance catalog (msgs={sig['msgs']}<{EARLY_ROMANCE_MAX_MSGS})"
        )

    recent_fams = _recent_families(exclude_names)
    ranked: List[Tuple[int, str, str, str]] = []
    for name, how in pool:
        sc, why = score_move(
            name,
            eff_pack=eff,
            sig=sig,
            recent_fams=recent_fams,
            turn_action=turn_action,
            unpaid=unpaid,
            no_lock=force_no_lock,
        )
        # Tiny hash jitter so ties don't stick forever
        jitter = int(
            __import__("hashlib")
            .md5(f"{fan_uuid}:{msgs}:{name}".encode())
            .hexdigest()[:2],
            16,
        ) % 3
        ranked.append((sc + jitter, name, how, why))

    ranked.sort(key=lambda x: x[0], reverse=True)
    best_score, name, how, why = ranked[0]
    fam, principle = manipulation.family_for(name)
    return ActiveMove(
        name=name,
        how=how,
        why=f"{why}|score={best_score}",
        family_id=fam,
        principle=principle,
    )


def turn_block(move: ActiveMove) -> str:
    """Compact TURN fact — playbook-aware when name is one of the 6."""
    pm = playbook.PLAYBOOK.get(move.name) or playbook._LEGACY_TO_PLAY.get(
        (move.name or "").upper()
    )
    if pm is not None:
        return playbook.turn_block(pm, why=move.why or "")
    fam_line = (
        f"- Family: {move.family_id} {move.principle}\n"
        if move.family_id
        else ""
    )
    why_line = f"- Why this move: {move.why}\n" if move.why else ""
    return (
        "ACTIVE MOVE THIS TURN (mandatory — not optional flirt):\n"
        f"{fam_line}"
        f"- Move: {move.name}\n"
        f"{why_line}"
        f"- How: {move.how}\n"
        "- Your bubble MUST execute this angle. Never name the technique.\n"
        "- Vary the example beat — do not copy it verbatim.\n"
        "- Do NOT fall back to generic cute chat or a random soft check-in.\n"
        "- HARD BAN: IRL meetups, sextortion/leaks, invent trauma not in CLIENT CARD."
    )


def author_steer(name: str) -> str:
    if not name:
        return ""
    return (
        f" Execute ACTIVE MOVE [{name}] — that angle is the point of this bubble. "
        f"Match its energy (see TURN example beat)."
    )


def reply_hits_move(reply: str, technique_name: str) -> bool:
    """True if reply shows a soft signal of the assigned move."""
    if not technique_name or not (reply or "").strip():
        return False
    if playbook.get_play_move(technique_name) is not None:
        return playbook.reply_hits_playbook(reply, technique_name)
    patterns = _MOVE_SIGNALS.get(technique_name) or ()
    if not patterns:
        return True
    text = reply.strip()
    return any(re.search(p, text) for p in patterns)


def is_rival_move(name: str) -> bool:
    return (name or "") in manipulation._RIVAL_TECHS
