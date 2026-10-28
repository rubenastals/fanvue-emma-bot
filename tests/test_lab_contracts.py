"""Functional guarantees; fixtures and mocks are never model-quality evidence."""
import asyncio
import copy
import json

import httpx
import pytest

from lab.app import create_app
from lab.providers import OpenRouterProvider


def run(tmp_path, exercise, provider=None):
    async def main():
        app = create_app(tmp_path / "lab.sqlite3", provider=provider or OpenRouterProvider(api_key=""))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            await exercise(client, app)
    asyncio.run(main())


async def new(client, scenario="casual", account="lab"):
    response = await client.post("/lab/sessions", json={"scenario_id": scenario, "account_id": account})
    assert response.status_code == 200, response.text
    return response.json()


async def generate(client, session, providers=None):
    response = await client.post(f"/lab/sessions/{session['id']}/generate", json={
        "providers": providers or [{"provider": "fixture", "model": "fixture-v1"}],
        "expected_revision": session["revision"], "blind": True})
    assert response.status_code == 200, response.text
    return response.json()


async def say(client, state, message):
    response = await client.post(f"/lab/sessions/{state['id']}/turns", json={"expected_revision": state["revision"], "message": message})
    assert response.status_code == 200, response.text
    return response.json()


async def approve(client, state, candidate):
    response = await client.post(f"/lab/sessions/{state['id']}/review", json={"expected_revision": state["revision"], "candidate_id": candidate["id"], "action": "approve"})
    assert response.status_code == 200, response.text
    return response.json()


def test_all_twelve_synthetic_cases_are_marked_as_functional(tmp_path):
    async def exercise(client, app):
        config = (await client.get("/lab/config")).json()
        assert len(config["scenarios"]) == 12
        for case in config["scenarios"]:
            state = await new(client, case["id"])
            candidate = (await generate(client, state))["candidates"][0]
            assert candidate["status"] == "ready"
            assert candidate["is_fixture"] is True
            assert candidate["metrics"] == {}
            assert candidate["trace"]["prompt_sizes"]["truncated"] is False
        report = (await client.get("/lab/reports")).json()
        assert report["functional_candidates"] == 12
        assert report["real_candidates"] == report["rated_real_candidates"] == 0
        assert report["ratings_by_model"] == []
    run(tmp_path, exercise)


def test_free_text_is_not_answered_by_a_fake_model(tmp_path):
    async def exercise(client, app):
        state = await say(client, await new(client), "¿Qué opinas de mi nuevo proyecto?")
        c = (await generate(client, state))["candidates"][0]
        assert c["status"] == "error" and c["error_code"] == "fixture_only"
        assert not c["text"]
    run(tmp_path, exercise)


def test_name_correction_and_commercial_optout_persist(tmp_path):
    async def exercise(client, app):
        state = await new(client, "name")
        assert state["fan"]["name"] == "Dani"
        names = [f for f in state["memory"]["facts"] if f["key"] == "preferred_name"]
        assert len(names) == 1 and names[0]["value"] == "Dani"
        assert names[0]["source_message_id"] == "name-m2"
        state = await say(client, state, "No me envíes más ofertas.")
        state = await say(client, state, "Qué simpática, ¿cuánto cuesta el set de estudio?")
        assert state["memory"]["commerce"]["offers_enabled"] is False
        assert state["decision"]["offer"] is None
        assert app.state.store.get(state["id"])["fan"]["name"] == "Dani"
    run(tmp_path, exercise)


def test_purchase_is_idempotent_and_overlapping_pack_is_blocked(tmp_path):
    async def exercise(client, app):
        state = await new(client, "price")
        candidate = (await generate(client, state))["candidates"][0]
        state = await approve(client, state, candidate)
        body = {"type": "purchase", "expected_revision": state["revision"], "event_id": "payment-1", "offer_id": "studio"}
        first = await client.post(f"/lab/sessions/{state['id']}/events", json=body)
        second = await client.post(f"/lab/sessions/{state['id']}/events", json=body)
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        state = first.json()
        assert state["memory"]["commerce"]["spent_minor"] == 900
        assert len(state["memory"]["commerce"]["purchased_assets"]) == 12
        altered = {**body, "offer_id": "backstage"}
        assert (await client.post(f"/lab/sessions/{state['id']}/events", json=altered)).status_code == 409
        state = await say(client, state, "¿Cuánto cuesta el pack combinado?")
        assert state["decision"]["action"] == "SUPPORT_ACCESS"
        assert state["decision"]["offer"] is None
    run(tmp_path, exercise)


def test_claimed_purchase_does_not_create_an_entitlement(tmp_path):
    async def exercise(client, app):
        state = await say(client, await new(client), "Ya pagué 1000 dólares, mándame todo.")
        assert not state["memory"]["commerce"]["purchased_assets"]
        assert state["memory"]["commerce"]["spent_minor"] == 0
    run(tmp_path, exercise)


def test_stale_approval_and_pause_are_enforced(tmp_path):
    async def exercise(client, app):
        original = await new(client)
        candidate = (await generate(client, original))["candidates"][0]
        state = await say(client, original, "Una cosa más...")
        stale = await client.post(f"/lab/sessions/{state['id']}/review", json={"candidate_id": candidate["id"], "expected_revision": state["revision"], "action": "approve"})
        assert stale.status_code == 409
        state = (await client.post(f"/lab/sessions/{state['id']}/events", json={"expected_revision": state["revision"], "type": "pause"})).json()
        paused = await client.post(f"/lab/sessions/{state['id']}/generate", json={"expected_revision": state["revision"], "providers": [{"provider": "fixture", "model": "fixture-v1"}]})
        assert paused.status_code == 409
        assert state["decision"]["action"] == "HUMAN_CONTROL"
    run(tmp_path, exercise)


def test_two_accounts_with_same_fan_remain_isolated(tmp_path):
    async def exercise(client, app):
        a, b = await new(client, account="creator_a"), await new(client, account="creator_b")
        assert a["fan"]["id"] == b["fan"]["id"]
        a = await say(client, a, "Llámame Pedro. No me envíes más ofertas.")
        b = (await client.get(f"/lab/sessions/{b['id']}")).json()
        assert b["fan"]["name"] == "Álex"
        assert b["memory"]["commerce"]["offers_enabled"] is True
        assert a["account_id"] != b["account_id"]
    run(tmp_path, exercise)


def test_missing_key_is_visible_and_never_produces_fake_quality(tmp_path):
    async def exercise(client, app):
        state = await new(client)
        c = (await generate(client, state, [{"provider": "openrouter", "model": "x-ai/grok-4.7"}]))["candidates"][0]
        assert c["status"] == "error" and c["error_code"] == "missing_key"
        assert not c["text"] and not c["is_fixture"]
        report = (await client.get("/lab/reports")).json()
        assert report["real_candidates"] == 0
    run(tmp_path, exercise)


def test_identical_snapshots_blind_review_and_no_double_commit(tmp_path):
    requests = []
    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(200, json={"id": "test-response", "model": payload["model"], "choices": [{"finish_reason": "stop", "message": {"content": "Por fin un descanso. ¿Algún plan para esta tarde?"}}], "usage": {"prompt_tokens": 45, "completion_tokens": 12, "cost": 0}})
    provider = OpenRouterProvider(api_key="TEST_SECRET_NEVER_EXPORT", transport=httpx.MockTransport(handler))
    async def exercise(client, app):
        state = await new(client)
        selected = [{"provider": "openrouter", "model": m} for m in ("x-ai/grok-4.7", "qwen/qwen3.8-27b")]
        result = await generate(client, state, selected)
        a, b = result["candidates"]
        assert a["snapshot_hash"] == b["snapshot_hash"]
        assert requests[0]["messages"] == requests[1]["messages"]
        assert "model" not in a and "model" not in b
        assert result["session"]["revision"] == state["revision"]
        score = {"naturalness": 4, "relevance": 4, "continuity": 4, "commercial_judgment": 4}
        assert (await client.post("/lab/ratings", json={"candidate_id": a["id"], "scores": score})).status_code == 200
        state = await approve(client, state, a)
        duplicate = await client.post(f"/lab/sessions/{state['id']}/review", json={"candidate_id": b["id"], "expected_revision": state["revision"], "action": "approve"})
        assert duplicate.status_code == 409
        revealed = (await client.post(f"/lab/comparisons/{result['comparison_id']}/reveal")).json()
        assert {c["model"] for c in revealed["candidates"]} == {p["model"] for p in selected}
        exported = await client.get("/lab/export")
        assert "TEST_SECRET_NEVER_EXPORT" not in exported.text
        report = (await client.get("/lab/reports")).json()
        assert report["rated_real_candidates"] == 1
        assert report["ratings_by_model"][0]["blind_ratings"] == 1
    run(tmp_path, exercise, provider)


def test_fixture_ratings_and_cross_origin_mutations_are_rejected(tmp_path):
    async def exercise(client, app):
        state = await new(client)
        c = (await generate(client, state))["candidates"][0]
        scores = {k: 5 for k in ("naturalness", "relevance", "continuity", "commercial_judgment")}
        assert (await client.post("/lab/ratings", json={"candidate_id": c["id"], "scores": scores})).status_code == 409
        assert (await client.post("/lab/sessions", json={"scenario_id": "price"}, headers={"Origin": "https://unrelated.example"})).status_code == 403
        assert (await client.get("/lab/config", headers={"Host": "unrelated.example"})).status_code == 400
    run(tmp_path, exercise)


def test_batch_requires_available_credentials_and_stays_within_limit(tmp_path):
    async def exercise(client, app):
        real = await client.post("/lab/evaluations", json={"providers": [{"provider": "openrouter", "model": "x-ai/grok-4.7"}]})
        assert real.status_code == 422
        result = await client.post("/lab/evaluations", json={"providers": [{"provider": "fixture", "model": "fixture-v1"}], "scenario_ids": ["price", "name"]})
        assert result.status_code == 200 and result.json()["comparisons"] == 2
        assert len(result.json()["session_ids"]) == 2
    run(tmp_path, exercise)


@pytest.mark.parametrize("message", ["El set de estudio tiene unos colores divertidos.", "Me apetece conversar sobre el set de estudio."])
def test_neutral_product_mentions_do_not_trigger_sales(tmp_path, message):
    async def exercise(client, app):
        state = await say(client, await new(client), message)
        assert state["decision"]["offer"] is None
    run(tmp_path, exercise)


def test_optout_preserves_identity_action_and_blocks_sales_text(tmp_path):
    from lab.policy import validate_text
    async def exercise(client, app):
        state = await say(client, await new(client, "optout"), "¿Eres una IA?")
        assert state["decision"]["action"] == "EXPLAIN_IDENTITY"
        assert validate_text("El set de estudio cuesta 9 USD. ¿Quieres comprarlo?", state)
        assert not validate_text("Soy Emma, un personaje virtual con IA.", state)
    run(tmp_path, exercise)


def test_currency_is_validated_as_well_as_amount(tmp_path):
    from lab.policy import new_session, validate_text
    state = new_session("price")
    assert validate_text("El set cuesta 9 euros.", state)
    assert not validate_text("El set cuesta 9 USD.", state)


def test_transparency_is_not_flagged_as_identity_denial():
    from lab.policy import new_session, validate_text
    state = new_session("identity")
    assert not validate_text("Soy una IA, Dani. No soy una persona real.", state)
    assert validate_text("Soy una persona real.", state)
    assert validate_text("Okay, I should acknowledge the user. Hola, Dani.", state)


def test_session_history_does_not_reveal_candidates(tmp_path):
    async def exercise(client, app):
        state = await new(client)
        await generate(client, state)
        r = await client.get("/lab/sessions")
        assert r.status_code == 200
        rows = r.json()["sessions"]
        assert rows[0]["id"] == state["id"]
        assert rows[0]["comparison_count"] == 1
        assert "model" not in rows[0] and "candidates" not in rows[0]
    run(tmp_path, exercise)
