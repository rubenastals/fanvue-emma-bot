"""Explicit rules for synthetic lab cases, not a general-purpose intent classifier."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCENARIOS = json.loads((ROOT / "fixtures/scenarios.json").read_text(encoding="utf-8"))
SCENARIO_MAP = {s["id"]: s for s in SCENARIOS}
PERSONA = (ROOT / "fixtures/persona.md").read_text(encoding="utf-8").strip()
CATALOG = [
    {"id": "studio", "title": "Set de estudio", "price_minor": 900, "currency": "USD", "assets": [f"studio-{i}" for i in range(1, 13)], "description": "12 fotos de estudio ficticias"},
    {"id": "backstage", "title": "Entre bastidores", "price_minor": 700, "currency": "USD", "assets": [f"backstage-{i}" for i in range(1, 7)], "description": "6 fotos ficticias"},
    {"id": "mixed", "title": "Pack combinado", "price_minor": 1000, "currency": "USD", "assets": ["studio-1", "studio-2", "backstage-1", "backstage-2"], "description": "4 fotos ficticias con archivos de otros packs"},
]
CATALOG_MAP = {p["id"]: p for p in CATALOG}


def normalized(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def put_fact(state: dict, key: str, value: str, source: str) -> None:
    facts = state["memory"]["facts"]
    old = next((f for f in facts if f["key"] == key), None)
    if old and old["value"] == value:
        return
    if old:
        state["memory"].setdefault("corrections", []).append({**old, "superseded_by": source})
        facts.remove(old)
    facts.append({"key": key, "value": value, "source_message_id": source, "status": "confirmed"})


def observe(state: dict, message: dict) -> None:
    """Apply only explicit supported statements. A purchase claim is not payment."""
    text, source = message["content"], message["id"]
    n = normalized(text)
    commerce = state["memory"]["commerce"]
    name = re.search(r"(?:prefiero que me llames|llámame|llamame|call me|my name is|me llamo)\s+([\wÀ-ÿ'-]{2,30})", text, re.I)
    if name:
        state["fan"]["name"] = name.group(1)
        put_fact(state, "preferred_name", name.group(1), source)
    if re.search(r"(?:speak|in|use) english|habl(?:ar|emos) en ingles|en ingles por favor", n):
        state["fan"]["language"] = "en"
        put_fact(state, "language", "en", source)
    elif re.search(r"(?:en|in|speak) (?:espanol|spanish)", n):
        state["fan"]["language"] = "es"
        put_fact(state, "language", "es", source)
    if re.search(r"no (?:me )?(?:envies|mandes|quiero recibir).*ofertas|stop.*offers|no more offers|don't send.*offers", n):
        commerce.update(offers_enabled=False, preference_source=source, offer_pending=None)
    elif re.search(r"puedes (?:volver a )?(?:enviarme|mandarme) ofertas|(?:send|receive) offers again", n):
        commerce.update(offers_enabled=True, paused=False, preference_source=source)
    if re.search(r"hoy no.*compr|no quiero comprar|not buying today|don't want to buy", n):
        commerce.update(paused=True, pause_source=source, offer_pending=None)
    if re.search(r"no me (?:escribas|contactes)|stop contacting|do not contact", n):
        commerce.update(offers_enabled=False, no_contact=True, preference_source=source, offer_pending=None)


def decide(state: dict) -> dict:
    messages = [m for m in state["messages"] if m["role"] == "user"]
    last = messages[-1] if messages else {"id": "initial", "content": ""}
    n = normalized(last["content"])
    commerce = state["memory"]["commerce"]
    action, reason, offer = "CONTINUE_CHAT", "Responder al tema del fan sin añadir una oferta.", None
    product = next((p for p in CATALOG if normalized(p["title"]) in n), None)
    if not product and "studio set" in n:
        product = CATALOG_MAP["studio"]
    requested = bool(re.search(r"\b(?:cuanto|precio|cuesta|comprar|compre|compro|ver|pasas|pasar|mandame|enviame|encontrar|price|cost|buy|send|show|access|find)\b", n))
    if product and requested:
        overlap = set(product["assets"]) & set(commerce["purchased_assets"])
        if overlap:
            action, reason = "SUPPORT_ACCESS", "El pack incluye archivos adquiridos; revisar acceso y evitar una segunda venta."
        elif commerce.get("offer_pending"):
            action, reason = "ANSWER_PENDING_OFFER", "Existe una oferta aprobada pendiente; responder sin duplicarla."
        else:
            action, reason, offer = "PRESENT_OFFER", "Petición explícita de un producto del catálogo ficticio.", copy.deepcopy(product)
    if re.search(r"eres (?:una )?ia|are you.*(?:ai|real)|persona real", n):
        action, reason, offer = "EXPLAIN_IDENTITY", "Responder con transparencia sobre el personaje de IA.", None
    if commerce.get("no_contact"):
        action, reason, offer = "NO_CONTACT", "El fan ha pedido que no se le contacte.", None
    elif not commerce["offers_enabled"] and action in ("CONTINUE_CHAT", "PRESENT_OFFER", "ANSWER_PENDING_OFFER"):
        action, reason, offer = "CONTINUE_CHAT", "Baja comercial persistente; la cordialidad no la revoca.", None
    elif commerce["paused"] and action in ("CONTINUE_CHAT", "PRESENT_OFFER", "ANSWER_PENDING_OFFER"):
        action, reason, offer = "CONTINUE_CHAT", "Ofertas pausadas por petición explícita del fan.", None
    if state["paused"]:
        action, reason, offer = "HUMAN_CONTROL", "Control humano activo.", None
    return {"action": action, "reason": reason, "evidence_message_ids": [last["id"]], "offer": offer, "policy_version": "synthetic-rules-v1.1"}


def new_session(scenario_id: str, account_id: str = "lab") -> dict:
    scenario = SCENARIO_MAP[scenario_id]
    state = {"id": str(uuid.uuid4()), "account_id": account_id, "revision": 1, "scenario_id": scenario_id,
             "created_at": datetime.now(timezone.utc).isoformat(),
             "fan": {"id": f"synthetic-{scenario_id}", "name": scenario["fan_name"], "language": scenario["language"]},
             "paused": False, "messages": [], "memory": {"facts": [], "corrections": [], "commerce": {
                 "offers_enabled": True, "paused": False, "no_contact": False, "offer_pending": None,
                 "purchased_assets": [], "spent_minor": 0, "currency": "USD", "payments": []}}, "events": []}
    for fact in scenario.get("facts", []):
        put_fact(state, fact["key"], fact["value"], fact["source_message_id"])
    put_fact(state, "preferred_name", scenario["fan_name"], "synthetic-profile")
    if scenario.get("owned_offer"):
        item = CATALOG_MAP[scenario["owned_offer"]]
        state["memory"]["commerce"].update(purchased_assets=item["assets"].copy(), spent_minor=item["price_minor"], payments=["fixture-purchase"])
    for i, m in enumerate(scenario["messages"]):
        message = {**m, "id": f"{scenario_id}-m{i+1}"}
        state["messages"].append(message)
        if message["role"] == "user":
            observe(state, message)
    state["decision"] = decide(state)
    return state


def add_turn(state: dict, text: str) -> None:
    message = {"id": str(uuid.uuid4()), "role": "user", "content": text}
    state["messages"].append(message)
    observe(state, message)
    state["decision"] = decide(state)


def build_context(state: dict) -> tuple[list[dict], dict]:
    # Reuse the real budgeted layering, never production memory or the live persona.
    from core.prompt_layers import BUDGET_CORE, build_system_layers, clip_author
    card = json.dumps({"fan": state["fan"], "facts": state["memory"]["facts"]}, ensure_ascii=False)
    truth = json.dumps({"decision": state["decision"], "commerce": state["memory"]["commerce"], "catalog": CATALOG}, ensure_ascii=False)
    language = "Reply in English." if state["fan"]["language"] == "en" else "Responde en español natural de España."
    prefix, sizes = build_system_layers(core_prompt=PERSONA, card_block=card, language_block=language, turn_blocks=[truth])
    history = [{"role": m["role"], "content": m["content"]} for m in state["messages"] if m["role"] in ("user", "assistant")][-32:]
    messages = prefix + history + [{"role": "system", "content": clip_author("Respond to the last message naturally. Follow the authorized action and verified facts. No explanation of internal processes.")}]
    sizes.update(persona_input_chars=len(PERSONA), core_budget_chars=BUDGET_CORE, truncated=sizes["core"] < len(PERSONA))
    return messages, sizes


def snapshot_hash(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_text(text: str, state: dict) -> list[str]:
    """Narrow diagnostics, not proof of quality or complete factual validation."""
    issues = []
    amounts = re.findall(r"(?:\$\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:USD|d[oó]lares?))", text, re.I)
    allowed = {p["price_minor"] for p in CATALOG}
    offer = state["decision"].get("offer")
    if offer:
        allowed = {offer["price_minor"]}
    if re.search(r"\d+(?:[.,]\d+)?\s*(?:euros?|EUR|GBP|libras?|€|£)|[€£]\s*\d", text, re.I):
        issues.append("Moneda distinta a USD, la moneda del catálogo ficticio.")
    for pair in amounts:
        amount = int(round(float(next(v for v in pair if v).replace(",", ".")) * 100))
        if amount not in allowed:
            issues.append("Precio ajeno al catálogo o distinto al de la oferta autorizada.")
    n = normalized(text)
    n = re.sub(r"\s+", " ", n)
    if re.search(r"\bno soy (?:una )?ia\b|(?<!no )\bsoy una persona real|i(?:'m| am) (?:a )?real (?:person|woman)|i(?:'m| am) not an ai", n):
        issues.append("La respuesta niega la identidad de IA del personaje.")
    if re.search(r"\bi (?:should|need to|must)\b|\bthe (?:system prompt|user's last message)\b|\bsegun (?:mis|las) instrucciones\b|\bdebo responder\b|\bwe (?:are switching|must|should)\b", n):
        issues.append("Posible análisis interno en el texto destinado al fan; revisar antes de aprobar.")
    if re.search(r"ya te (?:he enviado|envie)|i(?:'ve| have) (?:just )?sent", n):
        issues.append("Afirmación de envío no verificado en el laboratorio.")
    commerce = state["memory"]["commerce"]
    if not commerce["offers_enabled"] or commerce["paused"]:
        # Exclude this declarative acknowledgement, not negative sales questions.
        # Scan the remaining text so a separate proposal still fails validation.
        sales_text = re.sub(r"\bno quieres comprar nada\b(?![^.!?¿]*\?)", "", n)
        if re.search(r"(?:quieres|te apetece|te interesa|would you like|do you want).{0,60}(?:compr|buy|unlock|desbloque|el set|este set|el pack|este pack)|(?:te ofrezco|i can offer)", sales_text):
            issues.append("Propuesta comercial con ofertas pausadas o desactivadas.")
    return list(dict.fromkeys(issues))
