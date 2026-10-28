"""Local conversation lab. Run with python -m lab; never imports Fanvue clients."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
import secrets
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from lab import policy
from lab.providers import OpenRouterProvider, ProviderError
from lab.store import Conflict, LabStore, NotFound

ROOT = Path(__file__).resolve().parent


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SessionBody(StrictBody):
    scenario_id: str
    account_id: str = Field(default="lab", pattern=r"^[a-zA-Z0-9_-]{1,64}$")


class RevisionBody(StrictBody):
    expected_revision: int = Field(ge=1)


class TurnBody(RevisionBody):
    message: str = Field(min_length=1, max_length=4000)


class ProviderChoice(StrictBody):
    provider: Literal["fixture", "openrouter"]
    model: str = Field(min_length=1, max_length=160)
    provider_tag: str | None = Field(default=None, max_length=100)


class GenerateBody(RevisionBody):
    providers: list[ProviderChoice] = Field(min_length=1, max_length=4)
    blind: bool = True


class ReviewBody(RevisionBody):
    candidate_id: str
    action: Literal["approve", "reject"]
    edited_text: str | None = Field(default=None, max_length=6000)
    reviewer: Literal["operator", "test_harness"] = "operator"


class EventBody(RevisionBody):
    type: Literal["pause", "resume", "purchase"]
    event_id: str | None = Field(default=None, max_length=100)
    offer_id: str | None = None


class Scores(StrictBody):
    naturalness: int = Field(ge=1, le=5)
    relevance: int = Field(ge=1, le=5)
    continuity: int = Field(ge=1, le=5)
    commercial_judgment: int = Field(ge=1, le=5)


class RatingBody(StrictBody):
    candidate_id: str
    scores: Scores
    notes: str = Field(default="", max_length=2000)


class EvaluationBody(StrictBody):
    providers: list[ProviderChoice] = Field(min_length=1, max_length=4)
    scenario_ids: list[str] | None = None
    repetitions: int = Field(default=1, ge=1, le=2)


def public_candidate(c: dict) -> dict:
    result = copy.deepcopy(c)
    if c.get("text") and c.get("trace", {}).get("memory_used"):
        result["validation_issues"] = policy.validate_text(c["text"], {"memory": c["trace"]["memory_used"], "decision": c["trace"]["decision"]})
        result["validation_version"] = "lab-text-checks-v1.2"
    if not c["revealed"] and not c["is_fixture"]:
        for key in ("provider", "model", "returned_model", "upstream_provider", "response_id", "requested_provider_tag", "quantization", "request_settings", "routing_metadata"):
            result.pop(key, None)
        # Provider errors remain operationally visible, but never display the raw upstream body.
    return result


def create_app(db_path=None, provider: OpenRouterProvider | None = None) -> FastAPI:
    app = FastAPI(title="Fanv Conversation Lab", docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])
    store = LabStore(db_path or os.getenv("LAB_DATABASE_PATH", str(ROOT / ".data/lab.sqlite3")))
    router = provider or OpenRouterProvider()
    app.state.store, app.state.provider = store, router
    generation_slots = asyncio.Semaphore(4)
    batch_lock = asyncio.Lock()
    generating: set[str] = set()

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and urlparse(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "Origen de la solicitud no permitido."}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(NotFound)
    async def missing_handler(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ProviderError)
    async def provider_handler(request, exc):
        return JSONResponse({"detail": exc.message, "code": exc.code}, status_code=502)

    def session_view(state):
        return {**state, "candidates": [public_candidate(c) for c in store.candidates(sid=state["id"])]}

    @app.get("/lab/config")
    async def config():
        from core.prompt_layers import BUDGET_CORE
        live_persona = (ROOT.parent / "personas/emma.md").read_text(encoding="utf-8").strip()
        return {"mode": "isolated_lab", "live_sending": False,
                "providers": [
                    {"id": "fixture", "label": "Prueba funcional · sin IA", "configured": True, "models": [{"id": "fixture-v1", "label": "Ejemplos preparados"}]},
                    {"id": "openrouter", "label": "OpenRouter", "configured": router.configured, "models": router.public_models(),
                     "reason": None if router.configured else "Configura OPENROUTER_API_KEY en .env.lab y reinicia el laboratorio."}],
                "scenarios": [{k: s[k] for k in ("id", "title", "description", "language")} for s in policy.SCENARIOS],
                "catalog": policy.CATALOG, "catalog_fetched_at": router.fetched_at,
                "diagnostics": {"persona_input_chars": len(live_persona), "core_budget_chars": BUDGET_CORE,
                                "truncated": len(live_persona) > BUDGET_CORE, "scope": "default_repository_persona_static_check",
                                "lab_persona_chars": len(policy.PERSONA)},
                "evaluation": {"max_models": 4, "max_batch_calls": 48, "rubric": ["naturalness", "relevance", "continuity", "commercial_judgment"]}}

    @app.get("/lab/providers/openrouter/models")
    async def models():
        return {"models": await router.refresh_models(), "fetched_at": router.fetched_at}

    @app.post("/lab/sessions")
    async def new_session(body: SessionBody):
        if body.scenario_id not in policy.SCENARIO_MAP:
            raise HTTPException(422, "Caso de prueba desconocido.")
        return session_view(store.create(policy.new_session(body.scenario_id, body.account_id)))

    @app.get("/lab/sessions/{sid}")
    async def get_session(sid: str):
        return session_view(store.get(sid))

    @app.get("/lab/sessions")
    async def session_list():
        return {"sessions": store.list_sessions()}

    @app.post("/lab/sessions/{sid}/turns")
    async def turn(sid: str, body: TurnBody):
        def update(state):
            if len(state["messages"]) >= 200:
                raise Conflict("La sesión alcanzó 200 mensajes; crea un nuevo caso.")
            policy.add_turn(state, body.message)
        return session_view(store.mutate(sid, body.expected_revision, update))

    async def generate(sid: str, body: GenerateBody):
        if sid in generating:
            raise Conflict("Esta sesión ya tiene una comparación en curso.")
        state = store.get(sid)
        if state["revision"] != body.expected_revision:
            raise Conflict("El contexto cambió; recarga la sesión.")
        if state["paused"] or state["memory"]["commerce"].get("no_contact"):
            raise Conflict("La pausa o la petición de no contacto bloquea la generación.")
        choices = [p.model_dump() for p in body.providers]
        if len({(p["provider"], p["model"], p["provider_tag"]) for p in choices}) != len(choices):
            raise HTTPException(422, "No repitas el mismo modelo y proveedor en una comparación.")
        generating.add(sid)
        try:
            messages, sizes = policy.build_context(state)
            comparison_id, fingerprint = str(uuid.uuid4()), policy.snapshot_hash(state)
            # Labels are independent of selection order, persisted for later human review.
            secrets.SystemRandom().shuffle(choices)

            async def candidate(index, choice):
                c = {"id": str(uuid.uuid4()), "session_id": sid, "comparison_id": comparison_id,
                     "revision": state["revision"], "snapshot_hash": fingerprint, "label": chr(65 + index),
                     "provider": choice["provider"], "model": choice["model"], "is_fixture": choice["provider"] == "fixture",
                     "revealed": not body.blind, "review": "pending", "created_at": datetime.now(timezone.utc).isoformat(),
                     "text": "", "status": "error", "metrics": {}, "trace": {
                         "pipeline": "lab-v1: shared context, whitespace normalization, factual diagnostics; live sanitizer not applied",
                         "prompt_version": "lab-persona-" + hashlib.sha256(policy.PERSONA.encode()).hexdigest()[:12], "prompt_sizes": sizes, "messages": messages,
                         "memory_used": state["memory"], "decision": state["decision"], "stages": {}, "changes": []}}
                try:
                    if c["is_fixture"]:
                        initial = policy.new_session(state["scenario_id"])
                        original = [(m["role"], m["content"]) for m in initial["messages"]]
                        current = [(m["role"], m["content"]) for m in state["messages"]]
                        if choice["model"] != "fixture-v1" or current != original:
                            raise ProviderError("fixture_only", "Los ejemplos preparados solo responden al caso inicial. Conecta OpenRouter para probar mensajes libres.")
                        result = {"text": policy.SCENARIO_MAP[state["scenario_id"]]["fixture_reply"], "status": "ready", "metrics": {}}
                    else:
                        async with generation_slots:
                            result = await router.complete(choice["model"], copy.deepcopy(messages), choice["provider_tag"])
                    raw = result.pop("text")
                    c.update(result)
                    c["text"] = raw.strip()
                    c["trace"]["stages"] = {"original": raw, "first_sanitized": raw.strip(), "final": raw.strip()}
                    c["trace"]["changes"] = ["Trimmed boundary whitespace"] if raw != raw.strip() else []
                    c["validation_issues"] = policy.validate_text(c["text"], state)
                except ProviderError as exc:
                    c.update(error=exc.message, error_code=exc.code)
                return c

            candidates = await asyncio.gather(*(candidate(i, choice) for i, choice in enumerate(choices)))
            store.save_candidates(candidates)
            return {"comparison_id": comparison_id, "candidates": [public_candidate(c) for c in candidates], "session": session_view(store.get(sid))}
        finally:
            generating.discard(sid)

    @app.post("/lab/sessions/{sid}/generate")
    async def generate_endpoint(sid: str, body: GenerateBody):
        return await generate(sid, body)

    @app.post("/lab/sessions/{sid}/review")
    async def review(sid: str, body: ReviewBody):
        def update(state, candidate):
            text = body.edited_text if body.edited_text is not None else candidate["text"]
            if not text.strip():
                raise HTTPException(422, "El borrador no puede quedar vacío.")
            issues = policy.validate_text(text, state)
            if issues:
                raise Conflict("Revisa el borrador: " + " ".join(issues))
            candidate["approved_text"] = text
            candidate["reviewer"] = body.reviewer
            state["messages"].append({"id": str(uuid.uuid4()), "role": "assistant", "content": text, "candidate_id": candidate["id"]})
            offer = state["decision"].get("offer")
            if offer:
                state["memory"]["commerce"]["offer_pending"] = copy.deepcopy(offer)
            state["decision"] = policy.decide(state)
        return session_view(store.review(sid, body.candidate_id, body.expected_revision, body.action, update))

    @app.post("/lab/sessions/{sid}/events")
    async def event(sid: str, body: EventBody):
        if body.type == "purchase" and (not body.event_id or not body.offer_id):
            raise HTTPException(422, "Una compra necesita event_id y offer_id.")
        item = {"id": body.event_id or str(uuid.uuid4()), "type": body.type, "offer_id": body.offer_id}
        def update(state):
            if body.type in ("pause", "resume"):
                state["paused"] = body.type == "pause"
            else:
                commerce = state["memory"]["commerce"]
                offer = commerce.get("offer_pending")
                if not offer or offer["id"] != body.offer_id:
                    raise Conflict("La compra no corresponde a una oferta aprobada pendiente.")
                if set(offer["assets"]) & set(commerce["purchased_assets"]):
                    raise Conflict("El contenido ya se adquirió.")
                commerce["purchased_assets"].extend(offer["assets"])
                commerce["spent_minor"] += offer["price_minor"]
                commerce["payments"].append(body.event_id)
                commerce["offer_pending"] = None
                state["messages"].append({"id": body.event_id, "role": "event", "content": f"Compra ficticia: {offer['title']} · {offer['price_minor']/100:g} {offer['currency']}"})
            state["decision"] = policy.decide(state)
        return session_view(store.mutate(sid, body.expected_revision, update, event=item))

    @app.post("/lab/comparisons/{comparison_id}/reveal")
    async def reveal(comparison_id: str):
        return {"candidates": [public_candidate(c) for c in store.reveal(comparison_id)]}

    @app.post("/lab/ratings")
    async def rate(body: RatingBody):
        store.rate(body.candidate_id, body.scores.model_dump(), body.notes)
        return {"ok": True}

    @app.get("/lab/reports")
    async def reports():
        data = store.export()
        candidates = {c["id"]: c for c in data["candidates"]}
        session_cases = {s["id"]: s["scenario_id"] for s in data["sessions"]}
        groups = defaultdict(list)
        for rating in data["ratings"]:
            c = candidates[rating["candidate_id"]]
            if not c["is_fixture"] and c["status"] == "ready":
                groups[(c["provider"], c["model"], c.get("requested_provider_tag"))].append(rating)
        return {"real_candidates": sum(not c["is_fixture"] and c["status"] == "ready" for c in candidates.values()),
                "rated_real_candidates": sum(len(rows) for rows in groups.values()),
                "functional_candidates": sum(c["is_fixture"] for c in candidates.values()),
                "errors": sum(c["status"] == "error" for c in candidates.values()),
                "ratings_by_model": [{"provider": k[0], "model": k[1], "provider_tag": k[2], "count": len(rows),
                                      "blind_ratings": sum(r["blind_at_rating"] for r in rows),
                                      "case_counts": dict(Counter(session_cases[candidates[r["candidate_id"]]["session_id"]] for r in rows)),
                                      "scores": {axis: round(sum(r["scores"][axis] for r in rows)/len(rows), 2) for axis in Scores.model_fields}}
                                     for k, rows in groups.items()],
                "note": "Medias humanas descriptivas sin equilibrar casos. Revisa cobertura común antes de comparar. Las pruebas funcionales no miden calidad ni conversión."}

    @app.get("/lab/export")
    async def export():
        data = store.export()
        data.update(exported_at=datetime.now(timezone.utc).isoformat(), notice="Datos sintéticos. Exportar revela los modelos y proveedores.")
        return JSONResponse(data, headers={"Content-Disposition": 'attachment; filename="conversation-lab-results.json"'})

    @app.post("/lab/evaluations")
    async def evaluation(body: EvaluationBody):
        scenarios = body.scenario_ids or list(policy.SCENARIO_MAP)
        if not scenarios or any(s not in policy.SCENARIO_MAP for s in scenarios) or len(set(scenarios)) != len(scenarios):
            raise HTTPException(422, "Selecciona casos válidos sin duplicados.")
        if len(scenarios) * len(body.providers) * body.repetitions > 48:
            raise HTTPException(422, "Máximo de 48 respuestas por lote. Reduce modelos, casos o repeticiones.")
        if batch_lock.locked():
            raise Conflict("Ya hay un lote en curso.")
        if any(p.provider == "openrouter" for p in body.providers) and not router.configured:
            raise HTTPException(422, "Configura OpenRouter antes de iniciar un lote de modelos reales.")
        async with batch_lock:
            results = []
            for _ in range(body.repetitions):
                for scenario_id in scenarios:
                    state = store.create(policy.new_session(scenario_id))
                    results.append(await generate(state["id"], GenerateBody(providers=body.providers, expected_revision=state["revision"])))
        return {"run_id": str(uuid.uuid4()), "comparisons": len(results),
                "errors": sum(c["status"] == "error" for r in results for c in r["candidates"]),
                "session_ids": [r["session"]["id"] for r in results]}

    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "static/index.html")

    return app
