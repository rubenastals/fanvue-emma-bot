"""
Live per-turn psychology move (SIMPLE path).

Strategy = CODE picks the move from fan state + pack + ACTION.
Creativity = DeepSeek writes WhatsApp text for that move.
Compliance = soft signal check after draft (log / SCHEME), not another essay.

How-tos / instructions: English only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core import manipulation


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
        r"only\s+you|solo\s+t[uú]|thinking\s+about\s+you|pensando\s+en\s+ti)\b",
    ),
    "LOVE BOMBING (REWARD)": (
        r"(?i)\b(favorite|king|favorito|así\s+sí|thats?\s+why|my\s+favorite)\b",
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
    horny = bool(
        re.search(
            r"(?i)\b(hard|horny|cock|dick|pussy|fuck|cum|mojad|caliente|polla)\b",
            low,
        )
    )
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
    ) or (len(low) <= 28 and low.endswith("?"))
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
        "horny": horny,
        "soft_clarify": soft_clarify,
        "zero_spender": spent <= 0 and purchases <= 0,
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

    # Early chat → intimacy, not crisis/rival
    if sig["msgs"] < 4:
        if "LOVE BOMBING" in up or up == "MIRRORING":
            score += 12
            why.append("early-bond")
        if "EMERGENCY" in up or name in manipulation._RIVAL_TECHS:
            score -= 10
            why.append("too-early-for-pressure")

    # Zero spender mid-chat → commitment / intermittent (NOT silence-guilt)
    if sig["zero_spender"] and sig["msgs"] >= 4:
        if "MICRO COMMITMENT" in up or "INTERMITTENT" in up:
            score += 8
            why.append("zero-spender-hook")
        # After a free tease: push reciprocity/loyalty — never "you're quiet"
        # (live bug: GUILT fired mid-reply while he had JUST messaged).
        if sig["frees"] >= 1:
            if "LOYALTY" in up or "MICRO COMMITMENT" in up:
                score += 6
                why.append("free-given-reciprocity")
            if "GUILT" in up:
                score -= 8
                why.append("penalize-midchat-silence-guilt")

    # Heat / buy intent → close pressure
    if sig["buying"] or sig["horny"] or action == "attach_ppv":
        if "SCARCITY" in up or "FOMO" in up or "EGO" in up or "CLOSE" in up:
            score += 10
            why.append("heat-close")
        if "EMERGENCY" in up and not sig["price_push"]:
            score -= 4
            why.append("heat-not-crisis")

    # Unpaid lock → point at it / rival / guilt
    if unpaid or eff_pack == "ppv_unpaid":
        if "SCARCITY" in up or "FOMO" in up or "RIVAL" in up or "GUILT" in up:
            score += 9
            why.append("unpaid-pressure")
        if up == "FAKE EMERGENCY":
            score += 4
            why.append("unpaid-crisis-ok")

    # Price pushback → ladder + emergency + rival
    # Stale price_objection_step alone must NOT force crisis on soft check-ins
    objection_live = bool(
        sig["price_push"]
        or eff_pack == "price_objection"
        or (sig["reject_step"] > 0 and not sig.get("soft_clarify"))
    )
    if objection_live:
        if "GUILT" in up or "EGO" in up or "FOMO" in up or "EMERGENCY" in up:
            score += 8
            why.append("objection-ladder")
        if "WITHDRAWAL" in up and sig["reject_step"] >= 3:
            score += 10
            why.append("objection-exit")

    # Soft clarify ("pq lo dices?", "a grabar?") → bond/mirror, not crisis/rival
    if sig.get("soft_clarify"):
        if "EMERGENCY" in up or name in manipulation._RIVAL_TECHS:
            score -= 14
            why.append("clarify-not-crisis")
        if up in ("MIRRORING", "GASLIGHTING (soft)") or "LOVE BOMBING" in up:
            score += 6
            why.append("clarify-soft")

    # Reward pack
    if eff_pack == "reward_purchase":
        if "REWARD" in up or "LOVE BOMBING" in up:
            score += 15
            why.append("reward")
        else:
            score -= 20
            why.append("not-reward")

    # Pain map only when we have card facts and he's not brand new
    if "PAIN MAP" in up:
        if sig["cardish"] and sig["msgs"] >= 6 and not sig["price_push"]:
            score += 7
            why.append("card-pain")
        else:
            score -= 6
            why.append("no-pain-context")

    # Rival stronger when warm/spender or stuck zero after many msgs
    if name in manipulation._RIVAL_TECHS:
        if sig["msgs"] >= 8 and (sig["status"] in ("warm", "spender", "whale") or sig["zero_spender"]):
            score += 7
            why.append("rival-fit")
        if sig["msgs"] < 6:
            score -= 6
            why.append("rival-early")

    # Fake emergency: better when stalled / objection, not first flirts
    if "EMERGENCY" in up:
        if sig["reject_step"] >= 1 or sig["price_push"] or (unpaid and sig["msgs"] >= 10):
            score += 7
            why.append("crisis-when-stalled")
        elif sig["msgs"] < 8:
            score -= 8
            why.append("crisis-too-soon")

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
    price_objection keeps the 4-step ladder (with optional emergency spice).
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

    catalog = manipulation._filter_catalog(
        list(manipulation._TECH_BY_PACK.get(eff) or []),
        no_lock=force_no_lock,
        soft_support=soft_support,
        ban_rival_fan=ban_rival_fan,
    )
    exclude_u = {n.strip().upper() for n in (exclude_names or []) if n and n.strip()}
    if ban_withdrawal:
        exclude_u.add("LOVE BOMBING + WITHDRAWAL")
    pool = [(n, h) for n, h in catalog if n.upper() not in exclude_u] or list(catalog)
    if not pool:
        return None

    sig = _fan_signals(mem, fan_message)
    # Prefer live mem message count when present
    if mem is not None and int(mem.get("messages") or 0):
        sig["msgs"] = int(mem.get("messages") or msgs or 0)
    elif msgs:
        sig["msgs"] = msgs

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
    """Compact TURN fact — not the legacy CRITICAL essay banner."""
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
        "- HARD BAN: IRL meetups, sextortion/leaks, invent trauma not in CLIENT CARD.\n"
        "- Rival jealousy + fake emergency moves ARE allowed when this move says so."
    )


def author_steer(name: str) -> str:
    if not name:
        return ""
    return (
        f" Execute ACTIVE MOVE [{name}] — that angle is the point of this bubble."
    )


def reply_hits_move(reply: str, technique_name: str) -> bool:
    """True if reply shows a soft signal of the assigned move."""
    if not technique_name or not (reply or "").strip():
        return False
    patterns = _MOVE_SIGNALS.get(technique_name) or ()
    if not patterns:
        # Unknown move — don't false-fail
        return True
    text = reply.strip()
    return any(re.search(p, text) for p in patterns)


def is_rival_move(name: str) -> bool:
    return (name or "") in manipulation._RIVAL_TECHS
