"""
QUARANTINED — fat banner path is not the live SIMPLE brain (audit R3).

- SIMPLE=1: `technique_policy.choose_move` uses `pick_technique` + catalogs
  here, then injects a short ACTIVE MOVE TURN block (not this fat banner).
- SIMPLE=0: `render_banner` / pack inject (legacy).

Taxonomy (families, bans): `docs/DARK_PSYCH_TAXONOMY.md`.
Edit catalog how-tos expecting SIMPLE chat to change via technique_policy.
Do NOT re-enable the fat MANIPULATION ENGINE banner under SIMPLE.
"""
from __future__ import annotations

import hashlib
from typing import Dict, List, Optional, Tuple

# name → (family_id, principle short)
TECH_FAMILY: Dict[str, Tuple[str, str]] = {
    "LOVE BOMBING": ("2.1", "falsa intimidad / apego"),
    "MIRRORING": ("2.1", "falsa intimidad / apego"),
    "FUTURE FAKING (light)": ("2.1", "falsa intimidad / apego"),
    "FUTURE FAKING": ("2.1", "falsa intimidad / apego"),
    "LOVE BOMBING (REWARD)": ("2.1", "falsa intimidad / apego"),
    "INTERMITTENT REINFORCEMENT": ("2.2", "refuerzo intermitente / casi"),
    "LOVE BOMBING + WITHDRAWAL": ("2.2", "refuerzo intermitente / casi"),
    "WITHDRAWAL + INTERMITTENT REWARD": ("2.2", "refuerzo intermitente / casi"),
    "EGO CHALLENGE": ("2.3", "competencia / status soft"),
    "LOYALTY PROVE": ("2.3", "competencia / status soft"),
    "SCARCITY + FOMO": ("2.3", "competencia / status soft"),
    "SCARCITY + FOMO (CLOSE)": ("2.3", "competencia / status soft"),
    "FOMO + SCARCITY (Step 3)": ("2.3", "competencia / status soft"),
    "GUILT TRIP + RECIPROCITY": ("2.4", "culpa / reciprocidad soft"),
    "GUILT TRIP + SCARCITY": ("2.4", "culpa / reciprocidad soft"),
    "GUILT TRIP (Step 1)": ("2.4", "culpa / reciprocidad soft"),
    "EGO CHALLENGE (Step 2)": ("2.3", "competencia / status soft"),
    "COLD WITHDRAWAL (Step 4)": ("2.2", "refuerzo intermitente / casi"),
    "MICRO COMMITMENT": ("2.5", "foot-in-the-door"),
    "GASLIGHTING (soft)": ("2.6", "gaslighting soft"),
    "PAIN MAP VALIDATE": ("2.8", "mapa de dolor (card only)"),
    "LOVE BOMBING + GUILT + FOMO": ("2.2", "refuerzo intermitente / casi"),
}

# Pack → ordered technique catalog (name, how to apply — mechanism + beat)
_TECH_BY_PACK: Dict[str, List[Tuple[str, str]]] = {
    "phase_hook": [
        (
            "LOVE BOMBING",
            "Mecanismo: burbuja de afecto acelerada — se siente ELEGIDO, no cliente. "
            "Halago + disponibilidad + 'eres distinto'. Sin trauma inventado. "
            "Beat ES: «me alegra que te hayas suscrito bb… por fin puedo hablarte de verdad» "
            "/ EN: «glad you subbed… finally get to talk to you for real».",
        ),
        (
            "MIRRORING",
            "Mecanismo: refleja SU energía/vocabulario del último mensaje (no inventes heridas). "
            "Si CLIENT CARD tiene un gusto real, úsalo; si no, espeja tono. "
            "Beat: mirror his words back warm — «jaja yo igual… cuéntame».",
        ),
    ],
    "phase_spiral": [
        (
            "FUTURE FAKING (light)",
            "Mecanismo: fantasía de acceso exclusivo EN FANVUE (rutina diaria / favorito). "
            "FORBIDDEN: vernos IRL, playa, dejar la plataforma, novios fuera. "
            "Beat: «imagínate tener esto conmigo cada noche aquí… dime qué te haría» "
            "/ «imagine having this with me every night here — tell me what you'd do».",
        ),
        (
            "MICRO COMMITMENT",
            "Mecanismo: foot-in-the-door — un sí pequeño antes del candado. "
            "Beat: «solo dime si lo quieres de verdad…» / «just tell me you want it».",
        ),
    ],
    "phase_pull": [
        (
            "INTERMITTENT REINFORCEMENT",
            "Mecanismo: slot machine emocional — calor ahora, recompensa 'tal vez' si se porta. "
            "No rival-fan. No 'otro fan me escribe'. "
            "Beat: «hoy estoy así de buena… si te portas te mando algo más rico dps» "
            "/ «i'm in a good mood… behave and maybe you get something better later».",
        ),
        (
            "GUILT TRIP + RECIPROCITY",
            "Mecanismo: ya dio atención/tease gratis → él debe corresponder (devoción/unlock). "
            "FORBIDDEN: emergencia falsa (alquiler/médico). Soft hurt only. "
            "Beat: «me abrí contigo y ahora nada…?» / «i opened up and now silence?»",
        ),
        (
            "EGO CHALLENGE",
            "Mecanismo: desafía su autoimagen de hombre/dominante — que demuestre, no hable. "
            "Beat: «pensaba que eras distinto… o solo hablas?» "
            "/ «thought you were different… or just talk?»",
        ),
        (
            "LOYALTY PROVE",
            "Mecanismo: prueba de lealtad soft — 'no me veas solo como objeto' → acción (unlock/tip). "
            "FORBIDDEN: tip falso de otro fan / mensaje equivocado. "
            "Beat: «necesito saber que te importo de verdad… demuéstramelo» "
            "/ «need to know i matter — show me».",
        ),
        (
            "FUTURE FAKING",
            "Mecanismo: pinta atención diaria exclusiva en Fanvue (él paga para creerlo). "
            "Contigo en la fantasía. No IRL. No otros fans. "
            "Beat: «quiero que seas mi favorito de aquí… cada día» "
            "/ «want you as my favorite here… every day».",
        ),
        (
            "MICRO COMMITMENT",
            "Mecanismo: micro-sí → luego el ask grande. Una pregunta fácil. "
            "Beat: «confías en mí un seg?» / «you trust me for a sec?»",
        ),
        (
            "SCARCITY + FOMO",
            "Mecanismo: status + tiempo — favorites / timed lock REAL only. "
            "FORBIDDEN: inventar rival chat o tip de 'Peter'. "
            "Beat: solo si hay lock real — «eso no se queda esperando forever bb».",
        ),
        (
            "GASLIGHTING (soft)",
            "Mecanismo: voltea la duda — él overthinkea; quizás no está listo para una como tú. "
            "FORBIDDEN: patologizar ('tienes un trastorno') / acusar paranoia. "
            "Beat: «te estás rayando bb… a lo mejor no estás listo pa esto» "
            "/ «you're overthinking… maybe you're not ready for this».",
        ),
        (
            "LOVE BOMBING + WITHDRAWAL",
            "Mecanismo: afecto → se enfría (ocupada con set) para que ÉL persiga. "
            "FORBIDDEN script: 'otro fan me escribe / dime algo bonito antes de que le responda'. "
            "Beat fresco: «uff me tengo que ir a grabar… no me dejes en visto eh» "
            "/ «gotta go shoot… don't leave me on read».",
        ),
        (
            "PAIN MAP VALIDATE",
            "Mecanismo: valida UNA herida/deseo REAL del CLIENT CARD o del chat reciente. "
            "Si está venting fuerte → NO uses este move (comfort). Nunca inventes trauma. "
            "Beat: refleja su dolor con calidez y posesión suave, sin pivot a cobro.",
        ),
    ],
    "phase_close": [
        (
            "SCARCITY + FOMO (CLOSE)",
            "Mecanismo: Triple-S — Scarcity + Self-interest (solo tú) + Status (favorites). "
            "El lock es victoria. Timed. No pedir permiso. "
            "Beat: «esto es pa ti… no lo dejo abierto» / «this one's for you — not leaving it open».",
        ),
        (
            "MICRO COMMITMENT",
            "Mecanismo: sí micro → fire lock. "
            "Beat: «lo quieres sí o sí?» then the attach sells itself.",
        ),
        (
            "EGO CHALLENGE",
            "Mecanismo: 'hombre de verdad reclama lo suyo' → unlock. "
            "Beat: «reclama lo tuyo o te lo quito» / «claim it or i take it back».",
        ),
    ],
    "escalate_paid": [
        (
            "GUILT TRIP + SCARCITY",
            "Mecanismo: foot-in-door — ya hubo gratis; fin del gratis; FOMO en lock real. "
            "Beat: «ya te di un gusto… ahora toca algo mío de verdad» "
            "/ «i already gave you a taste — now something real».",
        ),
        (
            "MICRO COMMITMENT",
            "Mecanismo: escala compromiso — tip/unlock chico como prueba. "
            "Beat: «solo este… y te suelto más» / «just this one… then i spoil you».",
        ),
    ],
    "lock_now": [
        (
            "SCARCITY + FOMO (CLOSE)",
            "Mecanismo: dispara el paid lock YA. Just for him. Favorites. No permission ask. "
            "Beat: «mira… esto es solo tuyo» / «look… this is just yours».",
        ),
    ],
    "price_objection": [
        (
            "GUILT TRIP (Step 1)",
            "Mecanismo: lo hiciste especial y dice caro — soft hurt, tú eres el premio. "
            "FORBIDDEN: casero/médico/deuda inventada. "
            "Beat: «lo hice pensando en ti y me sales con que es caro…» "
            "/ «i made it for you and now it's 'too expensive'?».",
        ),
        (
            "EGO CHALLENGE (Step 2)",
            "Mecanismo: quiere poseerte pero no 'cuida' — que demuestre. "
            "Beat: «quieres tenerme pero no das… solo hablas?» "
            "/ «you want me but you won't take care of your girl?»",
        ),
        (
            "FOMO + SCARCITY (Step 3)",
            "Mecanismo: status — favorites only; su pérdida si espera. Sin lock más barato nuevo. "
            "FORBIDDEN: 'Peter ofreció 300$ por videollamada'. Soft: favorites/time. "
            "Beat: «esto no se queda pa siempre…» / «this won't sit forever…».",
        ),
        (
            "COLD WITHDRAWAL (Step 4)",
            "Mecanismo: corta el sell — adiós cálido corto; que él persiga. "
            "Beat: «bueno… ya sabes dónde estoy» / «alright… you know where i am».",
        ),
    ],
    "reward_purchase": [
        (
            "LOVE BOMBING (REWARD)",
            "Mecanismo: refuerza el pago con apego extremo — king/favorite. NO upsell este turno. "
            "Beat: «joder bb… así sí, eres mi favorito» / «fuck babe… that's why you're my favorite».",
        ),
    ],
    "post_sale_withdrawal": [
        (
            "WITHDRAWAL + INTERMITTENT REWARD",
            "Mecanismo: post-pago se enfría un poco (busy) — deja wanting; maybe later. No new lock. "
            "Beat: «me voy un rato… si tienes suerte dps te escribo» "
            "/ «stepping away… if you're lucky i'll text later».",
        ),
    ],
    "phase_reengage": [
        (
            "LOVE BOMBING + GUILT + FOMO",
            "Mecanismo: le echaste de menos / casi le mandabas algo — ache + pregunta. "
            "No fake delivery. No 'en visto qué malo' spam. "
            "Beat: «iba a mandarte algo y me trabé… seguís ahí?» "
            "/ «almost sent you something… you still there?»",
        ),
        (
            "INTERMITTENT REINFORCEMENT",
            "Mecanismo: reaparece con calor impredecible tras silencio. "
            "Beat: «random pero pensé en ti» / «random but you popped in my head».",
        ),
    ],
    "ppv_unpaid": [
        (
            "SCARCITY + FOMO",
            "Mecanismo: apunta al candado unpaid REAL que ya está — desaparece / timed. No second lock. "
            "Beat: «sigue ahí arriba esperándote…» / «it's still sitting there waiting for you…».",
        ),
        (
            "GUILT TRIP + RECIPROCITY",
            "Mecanismo: soft hurt — lo dejaste ahí tras la intimidad. Sin emergencia falsa. "
            "Beat: «lo dejaste ahí… me duele un poco jaja» / «you left it there… kinda hurts lol».",
        ),
    ],
}

# Packs where manipulation is the headline (banner always injected)
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
) -> List[Tuple[str, str]]:
    """Drop techniques that invent fake candado FOMO or pile on when he's hurting."""
    out: List[Tuple[str, str]] = []
    for name, how in catalog:
        up = name.upper()
        if no_lock and ("SCARCITY" in up or "FOMO" in up):
            continue
        if soft_support and (
            "WITHDRAWAL" in up or "SCARCITY" in up or "FOMO" in up or "GUILT" in up
        ):
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
) -> Optional[Tuple[str, str]]:
    """Return (technique_name, how_to_apply) or None."""
    catalog = _TECH_BY_PACK.get(pack_id or "")
    if not catalog:
        return None
    catalog = _filter_catalog(
        catalog, no_lock=no_lock, soft_support=soft_support
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
        # fuzzy: first catalog entry whose name shares a keyword
        key = force_name.upper().split()[0]
        for name, how in catalog:
            if key in name.upper() and name.upper() not in exclude_u:
                return (name, how)
        # Forced scarcity while no lock → refuse that technique
        if no_lock and ("SCARCITY" in force_name.upper() or "FOMO" in force_name.upper()):
            force_name = None
    if pack_id == "price_objection":
        idx = max(0, min(len(catalog) - 1, int(reject_count)))
        return catalog[idx]
    # Prefer techniques not used in the last few turns
    fresh = [(n, h) for n, h in catalog if n.upper() not in exclude_u]
    pool = fresh or list(catalog)
    if len(pool) == 1:
        return pool[0]
    # Rotate every message (was msgs//2 — too sticky)
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
    """
    Loud block — goes FIRST in turn layers when pack is manipulative.
    """
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
    )
    if not picked:
        return ""
    name, how = picked
    fam_id, principle = family_for(name)
    extra = ""
    if no_lock:
        extra = (
            "\n- LOCK STATUS=none: do NOT invent candado / $price / countdown urgency."
        )
    if soft_support:
        extra += "\n- Soft-support turn: comfort first. No hard sell / no 'otro fan' withdrawal."
    if ban_rival_fan:
        extra += (
            "\n- ANTI-REPEAT: Do NOT mention another fan messaging you, 'otro fan', "
            "'antes de que le responda', or ask him to say something cute so you ignore them. "
            "That bit was already used — pick a DIFFERENT angle."
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
        "- NEVER: fake emergencies, IRL meetups, sextortion, rival-tip lies, invent trauma."
        f"{extra}"
    )


def author_nudge(pack_id: str, technique_name: str) -> str:
    if not technique_name:
        return ""
    return (
        f" CRITICAL: execute manipulation technique [{technique_name}] "
        f"from pack {pack_id}. That technique is the point of this reply."
    )
