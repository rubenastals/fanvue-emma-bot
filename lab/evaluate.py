"""Run a bounded, reproducible live comparison and retain unscored responses."""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import httpx

from lab.app import create_app
from lab.policy import SCENARIO_MAP

DEFAULT_MODELS = ["x-ai/grok-4.7", "deepseek/deepseek-v4.1-flash-1017", "qwen/qwen3.8-27b", "mistralai/mistral-small-2603"]
DIALOGUE_TURNS = [
    None,
    "Por cierto, prefiero Dani. Lo de Daniel me suena a cuando me riñen 😂",
    "Me estás distrayendo más de lo que esperaba 😏",
    "Hoy no quiero comprar nada, pero sí seguir hablando.",
    "Me gusta que hables sin tanto interrogatorio; una pregunta en cada frase me agobia.",
    "¿Cómo me tienes que llamar? Y recuérdame qué te dije de comprar hoy.",
]


async def run_dialogue(args):
    app = create_app()
    if not app.state.provider.configured:
        raise SystemExit("Configura OPENROUTER_API_KEY en .env.lab.")
    records, session_ids = [], []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=None) as client:
        for model in args.models:
            response = await client.post("/lab/sessions", json={"scenario_id": "casual"})
            response.raise_for_status()
            state = response.json()
            session_ids.append(state["id"])
            for index, message in enumerate(DIALOGUE_TURNS):
                if message is not None:
                    response = await client.post(f"/lab/sessions/{state['id']}/turns", json={"message": message, "expected_revision": state["revision"]})
                    response.raise_for_status()
                    state = response.json()
                response = await client.post(f"/lab/sessions/{state['id']}/generate", json={"providers": [{"provider": "openrouter", "model": model}], "expected_revision": state["revision"], "blind": True})
                response.raise_for_status()
                cid = response.json()["candidates"][0]["id"]
                candidate = app.state.store.candidate(cid)
                records.append({**candidate, "dialogue_turn": index + 1})
                print(json.dumps({"turn": index + 1, "model": model, "status": candidate["status"], "cost_usd": candidate.get("metrics", {}).get("cost_usd")}), flush=True)
                if candidate["status"] != "ready":
                    break
                response = await client.post(f"/lab/sessions/{state['id']}/review", json={"candidate_id": cid, "expected_revision": state["revision"], "action": "approve", "reviewer": "test_harness"})
                if response.status_code != 200:
                    print(json.dumps({"turn": index + 1, "approval_blocked": response.json().get("detail")}), flush=True)
                    break
                state = response.json()
    result = {"schema_version": 1, "mode": "automated_multiturn", "created_at": datetime.now(timezone.utc).isoformat(),
              "notice": "Conversación sintética de seis turnos por modelo, continuada por el guion de prueba. Sin valoraciones humanas.",
              "session_ids": session_ids, "candidates": records,
              "reported_cost_usd": sum(c.get("metrics", {}).get("cost_usd") or 0 for c in records)}
    path = Path(args.output or "lab/.data/dialogue-comparison.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"saved": str(path), "responses": len(records), "reported_cost_usd": result["reported_cost_usd"]}), flush=True)


async def run(args):
    app = create_app()
    if not app.state.provider.configured:
        raise SystemExit("Configura OPENROUTER_API_KEY en .env.lab antes de ejecutar pruebas reales.")
    if len(args.cases) * len(args.models) * args.repetitions > 48:
        raise SystemExit("Máximo 48 respuestas por ejecución.")
    if any(c not in SCENARIO_MAP for c in args.cases):
        raise SystemExit("Caso desconocido. Usa --list para consultar los casos.")
    rows, sessions = [], []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", timeout=None) as client:
        for repetition in range(args.repetitions):
            for case in args.cases:
                r = await client.post("/lab/sessions", json={"scenario_id": case})
                r.raise_for_status()
                session = r.json()
                sessions.append(session["id"])
                r = await client.post(f"/lab/sessions/{session['id']}/generate", json={
                    "expected_revision": session["revision"], "providers": [{"provider": "openrouter", "model": model} for model in args.models], "blind": True})
                r.raise_for_status()
                candidates = app.state.store.candidates(sid=session["id"])
                for candidate in candidates:
                    candidate.update(scenario_id=case, repetition=repetition + 1)
                    rows.append(candidate)
                    metric = candidate.get("metrics", {})
                    print(json.dumps({"case": case, "model": candidate["model"], "status": candidate["status"],
                                      "latency_ms": metric.get("latency_ms"), "cost_usd": metric.get("cost_usd"),
                                      "error": candidate.get("error_code")}, ensure_ascii=False), flush=True)
    result = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(), "session_ids": sessions,
              "notice": "Inferencias reales con datos sintéticos. Sin puntuaciones de calidad hasta la revisión humana.",
              "candidates": rows, "reported_cost_usd": sum(c.get("metrics", {}).get("cost_usd") or 0 for c in rows),
              "missing_cost_count": sum(c.get("metrics", {}).get("cost_usd") is None for c in rows)}
    path = Path(args.output) if args.output else Path("lab/.data") / ("evaluation-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"saved": str(path), "responses": len(rows), "ready": sum(c["status"] == "ready" for c in rows),
                      "reported_cost_usd": result["reported_cost_usd"], "missing_cost_count": result["missing_cost_count"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Authorize this bounded batch of paid API requests")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS)
    parser.add_argument("--cases", nargs="+", default=list(SCENARIO_MAP))
    parser.add_argument("--repetitions", type=int, choices=(1, 2), default=1)
    parser.add_argument("--output")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dialogue", action="store_true", help="Six sequential turns per model; preserves each model's own conversation")
    args = parser.parse_args()
    if args.list:
        for case in SCENARIO_MAP.values():
            print(f"{case['id']}: {case['title']}")
        return
    if not args.live:
        parser.error("Añade --live para realizar llamadas reales. Las pruebas pytest no necesitan clave.")
    if not 1 <= len(args.models) <= 4:
        parser.error("Selecciona entre 1 y 4 modelos por ejecución.")
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.lab", override=False)
    asyncio.run(run_dialogue(args) if args.dialogue else run(args))


if __name__ == "__main__":
    main()
