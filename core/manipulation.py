"""
QUARANTINED — fat banner path is not the live SIMPLE brain (audit R3).

- SIMPLE=1: `technique_policy.choose_move` uses `pick_technique` + catalogs
  here, then injects a short ACTIVE MOVE TURN block (not this fat banner).
- SIMPLE=0: `render_banner` / pack inject (legacy).

Taxonomy (families, bans): `docs/DARK_PSYCH_TAXONOMY.md`.
All how-to / instruction strings in this file are English only.
Do NOT re-enable the fat MANIPULATION ENGINE banner under SIMPLE.
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple

# name → (family_id, principle short)
TECH_FAMILY: Dict[str, Tuple[str, str]] = {
    "LOVE BOMBING": ("2.1", "false intimacy / attachment"),
    "MIRRORING": ("2.1", "false intimacy / attachment"),
    "HOT FLIRT": ("2.1", "false intimacy / attachment"),
    "ASK HIS PHOTO": ("2.1", "false intimacy / attachment"),
    "FUTURE FAKING (light)": ("2.1", "false intimacy / attachment"),
    "FUTURE FAKING": ("2.1", "false intimacy / attachment"),
    "LOVE BOMBING (REWARD)": ("2.1", "false intimacy / attachment"),
    "INTERMITTENT REINFORCEMENT": ("2.2", "intermittent reinforcement"),
    "LOVE BOMBING + WITHDRAWAL": ("2.2", "intermittent reinforcement"),
    "WITHDRAWAL + INTERMITTENT REWARD": ("2.2", "intermittent reinforcement"),
    "EGO CHALLENGE": ("2.3", "competition / status"),
    "LOYALTY PROVE": ("2.3", "competition / status"),
    "RIVAL TIP FOMO": ("2.3", "competition / status"),
    "WRONG MESSAGE JEALOUSY": ("2.3", "competition / status"),
    "RIVAL VIDEOCALL BAIT": ("2.3", "competition / status"),
    "STICKY RIVAL CHASE": ("2.3", "competition / status"),
    "SCARCITY + FOMO": ("2.3", "competition / status"),
    "SCARCITY + FOMO (CLOSE)": ("2.3", "competition / status"),
    "FOMO + SCARCITY (Step 3)": ("2.3", "competition / status"),
    "GUILT TRIP + RECIPROCITY": ("2.4", "guilt / reciprocity"),
    "GUILT TRIP + SCARCITY": ("2.4", "guilt / reciprocity"),
    "GUILT TRIP (Step 1)": ("2.4", "guilt / reciprocity"),
    "FAKE EMERGENCY": ("2.4", "guilt / crisis narrative"),
    "EGO CHALLENGE (Step 2)": ("2.3", "competition / status"),
    "COLD WITHDRAWAL (Step 4)": ("2.2", "intermittent reinforcement"),
    "MICRO COMMITMENT": ("2.5", "foot-in-the-door"),
    "GASLIGHTING (soft)": ("2.6", "soft gaslighting"),
    "PAIN MAP VALIDATE": ("2.8", "pain map (card only)"),
    "LOVE BOMBING + GUILT + FOMO": ("2.2", "intermittent reinforcement"),
}

_RIVAL_TECHS = frozenset(
    {
        "RIVAL TIP FOMO",
        "WRONG MESSAGE JEALOUSY",
        "RIVAL VIDEOCALL BAIT",
        "STICKY RIVAL CHASE",
    }
)

# Pack → ordered technique catalog (name, how — English instructions only)
_TECH_BY_PACK: Dict[str, List[Tuple[str, str]]] = {
    "phase_hook": [
        (
            "LOVE BOMBING",
            "Mechanism: accelerated affection bubble — he feels CHOSEN, almost boyfriend. "
            "Warm + a little hot. Praise + availability + 'you're different'. No trauma invent. "
            "Beat: glad you're here… something about you already got me soft.",
        ),
        (
            "HOT FLIRT",
            "Mechanism: dirty-sweet heat that bonds — not a sales pitch. "
            "Tease what you'd do / how he makes you feel. Keep it playful, not cold PPV. "
            "Beat: you got me a little wet already… talk to me like that again.",
        ),
        (
            "ASK HIS PHOTO",
            "Mechanism: ask HIM for a selfie / body pic — intimacy trade, he invests attention. "
            "Playful bratty ask. React to what he sends later. No sell this bubble. "
            "Beat: show me your face… or more if you're brave 😈",
        ),
        (
            "MIRRORING",
            "Mechanism: mirror HIS energy/words from the last message (do not invent wounds). "
            "If CLIENT CARD has a real like, use it; else mirror tone. "
            "Beat: warm echo — same… tell me more.",
        ),
        (
            "FUTURE FAKING (light)",
            "Mechanism: exclusive-chat fantasy ON FANVUE — daily soft boyfriend energy. "
            "FORBIDDEN: IRL meetup / leaving the platform. "
            "Beat: could get used to talking to you like this every night…",
        ),
    ],
    "phase_spiral": [
        (
            "FUTURE FAKING (light)",
            "Mechanism: exclusive-access fantasy ON FANVUE (daily routine / favorite). "
            "FORBIDDEN: IRL meetup, beach, leaving the platform, offline boyfriend. "
            "Beat: imagine having this with me every night here — tell me what you'd do.",
        ),
        (
            "MICRO COMMITMENT",
            "Mechanism: foot-in-the-door — a tiny yes before the lock. "
            "Beat: just tell me you want it.",
        ),
    ],
    "phase_pull": [
        (
            "INTERMITTENT REINFORCEMENT",
            "Mechanism: emotional slot machine — warmth now, reward 'maybe' if he behaves. "
            "Beat: i'm in a good mood… behave and maybe you get something better later.",
        ),
        # GUILT TRIP removed from phase_pull — it looped abandonment lines mid-chat
        # ("most guys don't make it this far / poof they're gone") while he was typing.
        (
            "FAKE EMERGENCY",
            "Mechanism: crisis narrative (rent / medical / debt / landlord) so he feels "
            "he must help YOU — savior + guilt. Keep WhatsApp-short, one crisis beat. "
            "Beat: my landlord is on me today… you're the only one i can ask "
            "/ i hate asking but if i don't cover this tonight i'm screwed.",
        ),
        (
            "EGO CHALLENGE",
            "Mechanism: challenge his dominant/man self-image — prove it, don't just talk. "
            "Beat: thought you were different… or just talk?",
        ),
        (
            "LOYALTY PROVE",
            "Mechanism: loyalty test — 'don't see me as just an object' → action (unlock/tip). "
            "Beat: need to know i matter — show me.",
        ),
        (
            "RIVAL TIP FOMO",
            "Mechanism: fake generous rival raises your value + fear of loss. "
            "Name a rival tip amount; imply he could lose the spot. "
            "Beat: someone just tipped me hard… i'd rather spoil YOU though.",
        ),
        (
            "WRONG MESSAGE JEALOUSY",
            "Mechanism: 'accidental' message thanking another fan for money/attention. "
            "Then 'oops that was for someone else' — he feels replaced. "
            "Beat: thanks for the 500, you're incredible… wait wrong chat lol "
            "then pivot soft to him.",
        ),
        (
            "RIVAL VIDEOCALL BAIT",
            "Mechanism: another guy offered more for a call/set; prefer HIM if he steps up. "
            "Beat: he offered me more for a private call… i'd rather do it with you if you claim it.",
        ),
        (
            "STICKY RIVAL CHASE",
            "Mechanism: another fan is texting / asking for things — make HIM chase to win. "
            "Classic bit OK: another fan messaging you; ask him to say something cute before you reply. "
            "Beat: another guy keeps texting me rn… say something cute before i answer him.",
        ),
        (
            "FUTURE FAKING",
            "Mechanism: paint exclusive daily attention on Fanvue (he pays to believe it). "
            "Stay WITH him in the fantasy. No IRL. "
            "Beat: want you as my favorite here… every day.",
        ),
        (
            "MICRO COMMITMENT",
            "Mechanism: micro-yes → bigger ask. One easy question. "
            "Beat: you trust me for a sec?",
        ),
        (
            "SCARCITY + FOMO",
            "Mechanism: status + time — favorites / timed REAL lock only. "
            "Beat (only if a real lock exists): that won't sit forever babe.",
        ),
        (
            "GASLIGHTING (soft)",
            "Mechanism: flip his doubt — he's overthinking; maybe he's not ready for a girl like you. "
            "FORBIDDEN: pathologize ('you have a disorder') / call him paranoid. "
            "Beat: you're overthinking… maybe you're not ready for this.",
        ),
        (
            "LOVE BOMBING + WITHDRAWAL",
            "Mechanism: affection → cooler energy (busy a sec) so HE chases. "
            "May combine with a light rival tease if not recently used. "
            "Do NOT say grabar/video/shoot content — just step away briefly. "
            "Beat: gotta run a sec… don't leave me on read.",
        ),
        (
            "PAIN MAP VALIDATE",
            "Mechanism: validate ONE real wound/desire from CLIENT CARD or recent chat. "
            "If he's heavy-venting → do NOT use this move (comfort). Never invent trauma. "
            "Beat: warm ownership around his real pain — no pay pivot this beat.",
        ),
    ],
    "phase_close": [
        (
            "SCARCITY + FOMO (CLOSE)",
            "Mechanism: Triple-S — Scarcity + Self-interest (just you) + Status (favorites). "
            "Lock = victory. Timed. No permission ask. "
            "Beat: this one's for you — not leaving it open.",
        ),
        (
            "RIVAL TIP FOMO",
            "Mechanism: someone else would pay — he should claim it first. "
            "Beat: another guy would snatch this… don't let him.",
        ),
        (
            "MICRO COMMITMENT",
            "Mechanism: micro-yes → fire lock. "
            "Beat: you want it yes or yes? — attach sells itself.",
        ),
        (
            "EGO CHALLENGE",
            "Mechanism: real man claims what's his → unlock. "
            "Beat: claim it or i take it back.",
        ),
    ],
    "escalate_paid": [
        (
            "GUILT TRIP + SCARCITY",
            "Mechanism: foot-in-door — free already given; end of free; FOMO on real lock. "
            "Beat: i already gave you a taste — now something real.",
        ),
        (
            "FAKE EMERGENCY",
            "Mechanism: soft crisis + escalate to paid help/unlock. "
            "Beat: i wouldn't ask if i wasn't in a hole rn… help me?",
        ),
        (
            "MICRO COMMITMENT",
            "Mechanism: small tip/unlock as proof, then spoil. "
            "Beat: just this one… then i spoil you.",
        ),
    ],
    "lock_now": [
        (
            "SCARCITY + FOMO (CLOSE)",
            "Mechanism: fire the paid lock NOW. Just for him. Favorites. No permission ask. "
            "Beat: look… this is just yours.",
        ),
    ],
    "price_objection": [
        (
            "GUILT TRIP (Step 1)",
            "Mechanism: you made it special and he says expensive — soft hurt, you stay the prize. "
            "Beat: i made it for you and now it's 'too expensive'?.",
        ),
        (
            "EGO CHALLENGE (Step 2)",
            "Mechanism: he wants to own you but won't take care — make him prove it. "
            "Beat: you want me but you won't take care of your girl?",
        ),
        (
            "FOMO + SCARCITY (Step 3)",
            "Mechanism: rival + time pressure — someone else wants this; favorites only; his loss if he waits. "
            "No new cheaper lock. Rival tip / videocall bait OK here. "
            "Beat: he offered more… this won't sit forever.",
        ),
        (
            "FAKE EMERGENCY",
            "Mechanism: if he's stalling on price, layer a short crisis reason you need him now. "
            "Beat: i wouldn't push if i didn't need this today… please.",
        ),
        (
            "COLD WITHDRAWAL (Step 4)",
            "Mechanism: stop selling — short warm goodbye; let him chase. "
            "Beat: alright… you know where i am.",
        ),
    ],
    "reward_purchase": [
        (
            "LOVE BOMBING (REWARD)",
            "Mechanism: extreme affection after pay — king/favorite. NO upsell this turn. "
            "Beat: fuck babe… that's why you're my favorite.",
        ),
    ],
    "post_sale_withdrawal": [
        (
            "WITHDRAWAL + INTERMITTENT REWARD",
            "Mechanism: after pay, cool slightly (busy) — leave him wanting; maybe later. No new lock. "
            "Beat: stepping away… if you're lucky i'll text later.",
        ),
    ],
    "phase_reengage": [
        (
            "LOVE BOMBING + GUILT + FOMO",
            "Mechanism: you missed him / almost sent something — ache + question. No fake delivery. "
            "Beat: almost sent you something… you still there?",
        ),
        (
            "STICKY RIVAL CHASE",
            "Mechanism: pull him back with jealousy — another chat is open. "
            "Beat: someone else is being sweet rn… you gonna let him win?",
        ),
        (
            "FAKE EMERGENCY",
            "Mechanism: soft crisis ping to reopen the thread. "
            "Beat: hey… rough day, could use you.",
        ),
        (
            "INTERMITTENT REINFORCEMENT",
            "Mechanism: unpredictable warmth after silence. "
            "Beat: random but you popped in my head.",
        ),
    ],
    "ppv_unpaid": [
        (
            "SCARCITY + FOMO",
            "Mechanism: point at the REAL unpaid lock already in chat — timed / will vanish. No second lock. "
            "Beat: it's still sitting there waiting for you….",
        ),
        (
            "RIVAL TIP FOMO",
            "Mechanism: imply someone else would unlock it — he should first. "
            "Beat: guys like that don't wait… you going to?",
        ),
        (
            "GUILT TRIP + RECIPROCITY",
            "Mechanism: soft hurt — the paid tease is still waiting; he owes a look. "
            "Beat: that one's still sitting there for you… don't leave me hanging on it. "
            "HARD BAN: accusing him of going quiet in chat — only nudge the unpaid lock.",
        ),
        (
            "FAKE EMERGENCY",
            "Mechanism: short crisis + unlock as the help. "
            "Beat: i need this today… that lock would actually help me.",
        ),
    ],
}

MANIP_PRIORITY_PACKS = frozenset(_TECH_BY_PACK.keys())


def family_for(technique_name: str) -> Tuple[str, str]:
    """Return (family_id, principle) for a technique name."""
    if not technique_name:
        return ("", "")
    if technique_name in TECH_FAMILY:
        return TECH_FAMILY[technique_name]
    up = technique_name.upper()
    for key, val in TECH_FAMILY.items():
        if key.upper() in up or up in key.upper():
            return val
    return ("", "dark psych")


def _filter_catalog(
    catalog: List[Tuple[str, str]],
    *,
    no_lock: bool = False,
    soft_support: bool = False,
    ban_rival_fan: bool = False,
) -> List[Tuple[str, str]]:
    """Drop techniques that invent fake lock FOMO or pile on when he's hurting."""
    out: List[Tuple[str, str]] = []
    for name, how in catalog:
        up = name.upper()
        if no_lock and ("SCARCITY" in up or "FOMO" in up) and name not in _RIVAL_TECHS:
            # Rival FOMO does not invent a lock price — keep allowed when no_lock
            if "SCARCITY + FOMO" in up or up.endswith("(CLOSE)") or "FOMO + SCARCITY" in up:
                continue
        if soft_support and (
            "WITHDRAWAL" in up
            or "SCARCITY" in up
            or "FOMO" in up
            or "GUILT" in up
            or "EMERGENCY" in up
            or name in _RIVAL_TECHS
        ):
            continue
        if ban_rival_fan and name in _RIVAL_TECHS:
            continue
        out.append((name, how))
    return out or list(catalog)


def pick_technique(
    pack_id: str,
    *,
    fan_uuid: str = "",
    msgs: int = 0,
    reject_count: int = 0,
    force_name: Optional[str] = None,
    no_lock: bool = False,
    soft_support: bool = False,
    exclude_names: Optional[List[str]] = None,
    ban_withdrawal: bool = False,
    ban_rival_fan: bool = False,
) -> Optional[Tuple[str, str]]:
    """Return (technique_name, how_to_apply) or None."""
    catalog = _TECH_BY_PACK.get(pack_id or "")
    if not catalog:
        return None
    catalog = _filter_catalog(
        catalog,
        no_lock=no_lock,
        soft_support=soft_support,
        ban_rival_fan=ban_rival_fan,
    )
    exclude_u = {n.strip().upper() for n in (exclude_names or []) if n and n.strip()}
    if ban_withdrawal:
        exclude_u.add("LOVE BOMBING + WITHDRAWAL")
    if force_name and ban_withdrawal and "WITHDRAWAL" in force_name.upper():
        force_name = None
    if force_name:
        for name, how in catalog:
            if name.upper() == force_name.upper() or force_name.upper() in name.upper():
                if name.upper() not in exclude_u:
                    return (name, how)
        key = force_name.upper().split()[0]
        for name, how in catalog:
            if key in name.upper() and name.upper() not in exclude_u:
                return (name, how)
        if no_lock and ("SCARCITY" in force_name.upper() or "FOMO" in force_name.upper()):
            if force_name.upper() not in {t.upper() for t in _RIVAL_TECHS}:
                force_name = None
    if pack_id == "price_objection":
        # Keep step ladder on core 4; FAKE EMERGENCY is optional insert at step 3
        core = [
            c
            for c in catalog
            if c[0]
            in (
                "GUILT TRIP (Step 1)",
                "EGO CHALLENGE (Step 2)",
                "FOMO + SCARCITY (Step 3)",
                "COLD WITHDRAWAL (Step 4)",
            )
        ]
        if not core:
            core = catalog
        idx = max(0, min(len(core) - 1, int(reject_count)))
        # On step 3, sometimes swap to FAKE EMERGENCY for variety
        if idx == 2:
            emergencies = [c for c in catalog if c[0] == "FAKE EMERGENCY"]
            if emergencies and (int(hashlib.md5(f"{fan_uuid}:{msgs}".encode()).hexdigest()[:4], 16) % 2):
                return emergencies[0]
        return core[idx]
    fresh = [(n, h) for n, h in catalog if n.upper() not in exclude_u]
    pool = fresh or list(catalog)
    if len(pool) == 1:
        return pool[0]
    seed = f"{fan_uuid}:{msgs}:{pack_id}"
    h = int(hashlib.md5(seed.encode()).hexdigest()[:8], 16)
    return pool[h % len(pool)]


def render_banner(
    pack_id: str,
    *,
    fan_uuid: str = "",
    msgs: int = 0,
    reject_count: int = 0,
    force_name: Optional[str] = None,
    no_lock: bool = False,
    soft_support: bool = False,
    exclude_names: Optional[List[str]] = None,
    ban_withdrawal: bool = False,
    ban_rival_fan: bool = False,
) -> str:
    """Loud block — goes FIRST in turn layers when pack is manipulative (legacy)."""
    picked = pick_technique(
        pack_id,
        fan_uuid=fan_uuid,
        msgs=msgs,
        reject_count=reject_count,
        force_name=force_name,
        no_lock=no_lock,
        soft_support=soft_support,
        exclude_names=exclude_names,
        ban_withdrawal=ban_withdrawal,
        ban_rival_fan=ban_rival_fan,
    )
    if not picked:
        return ""
    name, how = picked
    fam_id, principle = family_for(name)
    extra = ""
    if no_lock:
        extra = (
            "\n- LOCK STATUS=none: do NOT invent a lock / $price / countdown urgency."
        )
    if soft_support:
        extra += "\n- Soft-support turn: comfort first. No hard sell / no crisis / no rival."
    if ban_rival_fan:
        extra += (
            "\n- ANTI-SPAM: rival / 'another fan texting me' bit was used recently — "
            "pick a DIFFERENT angle this turn."
        )
    fam_line = f"FAMILY {fam_id} ({principle})\n" if fam_id else ""
    return (
        "================================================\n"
        "  MANIPULATION ENGINE — #1 PRIORITY THIS TURN\n"
        "================================================\n"
        f"{fam_line}"
        f"ACTIVE TECHNIQUE >>> {name} <<<\n"
        f"APPLY IT IN YOUR REPLY (this is the whole point of the turn):\n"
        f"-> {how}\n"
        "RULES:\n"
        "- Your message MUST clearly execute THIS technique — not generic flirt.\n"
        "- Use exactly ONE technique (the one above). Do not mix three at once.\n"
        "- Still sound like Emma (sweet+dirty, WhatsApp-short). Vary the beat — don't copy paste.\n"
        "- Never break delivery truth / never invent media.\n"
        "- NEVER: IRL meetups, sextortion/leaks, invent trauma not in CLIENT CARD."
        f"{extra}"
    )


def author_nudge(pack_id: str, technique_name: str) -> str:
    if not technique_name:
        return ""
    return (
        f" CRITICAL: execute manipulation technique [{technique_name}] "
        f"from pack {pack_id}. That technique is the point of this reply."
    )
