"""Transport contracts only: these tests do not measure conversation quality."""
import asyncio
import copy
import json
import logging

import httpx
import pytest

from lab import providers as provider_module
from lab.providers import OpenRouterProvider, ProviderError


MODEL = "test/model-v1"
TAG = "test-provider/bf16"
TEST_KEY = "sk-or-synthetic-test-key"
MESSAGES = [{"role": "system", "content": "Synthetic persona."},
            {"role": "user", "content": "PRIVATE_SYNTHETIC_MESSAGE: ¿Cuánto cuesta el set?"}]


def completion(**overrides):
    data = {
        "id": "gen-synthetic-1", "model": MODEL,
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "El set cuesta 9 USD."}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28, "cost": 0.0001},
    }
    data.update(overrides)
    return data


def provider(handler, *, pinned=True, supported=None):
    adapter = OpenRouterProvider(api_key=TEST_KEY, transport=httpx.MockTransport(handler))
    adapter.models = {MODEL: {"id": MODEL, "name": "Synthetic model", "context_length": 10000,
                             "supported_parameters": ["reasoning", "max_tokens"]}}
    adapter.pins = {MODEL: {"tag": TAG, "quantization": "bf16", "status": 0,
                           "supported_parameters": ["reasoning", "max_tokens"] if supported is None else supported}} if pinned else {}
    return adapter


def run_complete(adapter, **kwargs):
    return asyncio.run(adapter.complete(MODEL, copy.deepcopy(MESSAGES), **kwargs))


def test_explicit_model_pinned_provider_and_private_request_settings(caplog):
    requests = []

    def handler(request):
        requests.append(request)
        assert request.method == "POST"
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {TEST_KEY}"
        assert request.headers["X-OpenRouter-Metadata"] == "enabled"
        body = json.loads(request.content)
        assert body["model"] == MODEL
        assert body["messages"] == MESSAGES
        assert body["max_completion_tokens"] == 1024
        assert "max_tokens" not in body and "models" not in body and "route" not in body
        assert body["provider"] == {"order": [TAG], "only": [TAG], "allow_fallbacks": False,
                                    "require_parameters": True, "data_collection": "deny"}
        assert body["reasoning"] == {"effort": "low", "exclude": True}
        return httpx.Response(200, json=completion())

    caplog.set_level(logging.DEBUG)
    result = run_complete(provider(handler))
    assert len(requests) == 1 and result["status"] == "ready"
    assert result["returned_model"] == MODEL
    assert "messages" not in result["request_settings"]
    assert TEST_KEY not in json.dumps(result) + caplog.text
    assert "PRIVATE_SYNTHETIC_MESSAGE" not in json.dumps(result) + caplog.text


def test_endpoint_capabilities_override_model_capabilities():
    def handler(request):
        assert "reasoning" not in json.loads(request.content)
        return httpx.Response(200, json=completion())

    assert run_complete(provider(handler, supported=[]))["status"] == "ready"


def test_actual_provider_comes_from_selected_router_metadata():
    metadata = {"attempt": 1, "endpoints": {"available": [
        {"provider": "Unused", "model": MODEL, "selected": False},
        {"provider": "Observed backend", "model": MODEL, "selected": True}]},
        "pipeline": [{"type": "context_compression", "name": "middle-out"}]}
    adapter = provider(lambda request: httpx.Response(200, json=completion(
        provider="Unverified top-level field", openrouter_metadata=metadata)))
    result = run_complete(adapter)
    assert result["upstream_provider"] == "Observed backend"
    assert result["routing_metadata"] == metadata
    assert result["requested_provider_tag"] == TAG


@pytest.mark.parametrize("metadata", [None, {}, [], {"endpoints": None},
    {"endpoints": {"available": [{"provider": "Not selected", "selected": False}]}},
    {"endpoints": {"available": [{"provider": "A", "selected": True}, {"provider": "B", "selected": True}]}}])
def test_missing_or_ambiguous_actual_provider_is_not_inferred_from_pin(metadata):
    adapter = provider(lambda request: httpx.Response(200, json=completion(
        provider="Configured but unverified", openrouter_metadata=metadata)))
    assert run_complete(adapter)["upstream_provider"] == "unreported"


def test_zero_cost_usage_reasoning_and_cache_are_preserved():
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0,
             "prompt_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
             "completion_tokens_details": {"reasoning_tokens": 0}}
    metrics = run_complete(provider(lambda request: httpx.Response(200, json=completion(usage=usage))))["metrics"]
    for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd", "reasoning_tokens",
                "cached_input_tokens", "cache_write_tokens"):
        assert metrics[key] == 0


@pytest.mark.parametrize("usage", [None, [], "invalid", {"prompt_tokens": True, "completion_tokens": -1,
    "cost": "unknown", "prompt_tokens_details": [], "completion_tokens_details": 5}])
def test_missing_or_malformed_usage_is_not_reported_as_zero(usage):
    result = run_complete(provider(lambda request: httpx.Response(200, json=completion(usage=usage))))
    assert result["status"] == "ready"
    for key in ("input_tokens", "output_tokens", "total_tokens", "cost_usd", "reasoning_tokens", "cached_input_tokens"):
        assert result["metrics"][key] is None


@pytest.mark.parametrize("finish", [None, "length", "tool_calls", "unexpected", {}])
def test_partial_or_uncertain_finish_is_incomplete(finish):
    response = completion()
    response["choices"][0]["finish_reason"] = finish
    result = run_complete(provider(lambda request: httpx.Response(200, json=response)))
    assert result["status"] == "incomplete" and result["text"]


def test_explicit_incomplete_status_prevents_ready():
    result = run_complete(provider(lambda request: httpx.Response(200, json=completion(status="incomplete"))))
    assert result["status"] == "incomplete"


@pytest.mark.parametrize("choices", [[], None, [None], [{"message": None}],
    [{"message": {"content": None}}], [{"message": {"content": "   "}}]])
def test_empty_or_malformed_choices_fail_explicitly(choices):
    with pytest.raises(ProviderError) as exc:
        run_complete(provider(lambda request: httpx.Response(200, json=completion(choices=choices))))
    assert exc.value.code == "empty_response"


@pytest.mark.parametrize("finish,refusal", [("content_filter", None), ("refusal", None), ("stop", "Policy refusal")])
def test_refusal_is_not_scored_as_a_ready_candidate(finish, refusal):
    data = completion()
    data["choices"][0].update(finish_reason=finish)
    data["choices"][0]["message"]["refusal"] = refusal
    with pytest.raises(ProviderError) as exc:
        run_complete(provider(lambda request: httpx.Response(200, json=data)))
    assert exc.value.code == "refused"


@pytest.mark.parametrize("failure", ["envelope", "choice", "finish", "status"])
def test_generation_errors_do_not_return_success(failure):
    data = completion()
    if failure == "envelope":
        data["error"] = {"message": TEST_KEY + MESSAGES[-1]["content"]}
    elif failure == "choice":
        data["choices"][0]["error"] = {"message": TEST_KEY}
    elif failure == "finish":
        data["choices"][0]["finish_reason"] = "error"
    else:
        data["status"] = "failed"
    with pytest.raises(ProviderError) as exc:
        run_complete(provider(lambda request: httpx.Response(200, json=data)))
    assert exc.value.code == "provider_error"
    assert TEST_KEY not in str(exc.value) and "PRIVATE_SYNTHETIC_MESSAGE" not in str(exc.value)


@pytest.mark.parametrize("status", [401, 402, 404, 429, 500, 302])
def test_http_errors_are_redacted_and_never_retried(status, caplog):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, text=TEST_KEY + MESSAGES[-1]["content"], headers={"Location": "https://unexpected.example"})

    caplog.set_level(logging.DEBUG)
    with pytest.raises(ProviderError) as exc:
        run_complete(provider(handler))
    assert exc.value.code == f"http_{status}"
    assert len(calls) == 1
    assert TEST_KEY not in str(exc.value) + caplog.text
    assert "PRIVATE_SYNTHETIC_MESSAGE" not in str(exc.value) + caplog.text


@pytest.mark.parametrize("exception,code", [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "connection_error")])
def test_transport_errors_do_not_expose_upstream_exception(exception, code):
    calls = []

    def handler(request):
        calls.append(request)
        raise exception(TEST_KEY + MESSAGES[-1]["content"], request=request)

    with pytest.raises(ProviderError) as exc:
        run_complete(provider(handler))
    assert exc.value.code == code and len(calls) == 1
    assert TEST_KEY not in str(exc.value) and "PRIVATE_SYNTHETIC_MESSAGE" not in str(exc.value)
    assert exc.value.__suppress_context__


def test_unpinned_endpoint_is_selected_once_and_stays_stable():
    paths, tags = [], []

    def handler(request):
        paths.append(request.url.path)
        if request.method == "GET":
            assert "Authorization" not in request.headers
            return httpx.Response(200, json={"data": {"endpoints": [
                {"tag": "alternate/fp4", "quantization": "fp4", "status": 0},
                {"tag": TAG, "quantization": "bf16", "status": 0}]}})
        tags.append(json.loads(request.content)["provider"]["only"])
        return httpx.Response(200, json=completion())

    adapter = provider(handler, pinned=False)
    run_complete(adapter)
    run_complete(adapter)
    assert paths.count("/api/v1/models/test/model-v1/endpoints") == 1
    assert tags == [[TAG], [TAG]]


def test_explicit_endpoint_pin_is_stable_and_does_not_replace_default():
    requested = "another-provider/fp16"
    gets, tags = [], []

    def handler(request):
        if request.method == "GET":
            gets.append(request.url.path)
            return httpx.Response(200, json={"data": {"endpoints": [{"tag": requested, "status": 0}]}})
        tags.append(json.loads(request.content)["provider"]["only"])
        return httpx.Response(200, json=completion())

    adapter = provider(handler)
    run_complete(adapter, provider_tag=requested)
    run_complete(adapter, provider_tag=requested)
    run_complete(adapter)
    assert len(gets) == 1
    assert tags == [[requested], [requested], [TAG]]


def test_unavailable_requested_endpoint_never_substitutes_another():
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={"data": {"endpoints": [{"tag": "other/fp16", "status": 0}]}})

    with pytest.raises(ProviderError) as exc:
        run_complete(provider(handler), provider_tag="missing/fp16")
    assert exc.value.code == "no_endpoint" and calls == ["GET"]


def test_failed_pinned_endpoint_does_not_refresh_or_repin():
    calls = []

    def handler(request):
        calls.append(request.method)
        return httpx.Response(503, json={"error": {"message": "Unavailable"}})

    adapter = provider(handler)
    for _ in range(2):
        with pytest.raises(ProviderError):
            run_complete(adapter)
    assert calls == ["POST", "POST"] and adapter.pins[MODEL]["tag"] == TAG


def test_refresh_catalog_is_public_and_preserves_existing_provider_pin():
    def handler(request):
        assert request.method == "GET" and request.url.path == "/api/v1/models"
        assert "Authorization" not in request.headers
        return httpx.Response(200, json={"data": [None, {"id": []},
            {"id": MODEL, "name": "Updated name", "architecture": {"output_modalities": ["text"]}},
            {"id": "test/image", "architecture": {"output_modalities": ["image"]}}]})

    adapter = provider(handler)
    models = asyncio.run(adapter.refresh_models())
    assert models[0]["label"] == "Updated name" and models[0]["provider_tag"] == TAG
    assert "test/image" not in adapter.models and adapter.fetched_at


def test_missing_key_and_router_alias_do_not_make_requests():
    def handler(request):
        pytest.fail("An invalid configuration must not issue a request")

    adapter = provider(handler)
    adapter._key = ""
    with pytest.raises(ProviderError) as exc:
        run_complete(adapter)
    assert exc.value.code == "missing_key"
    adapter._key = TEST_KEY
    adapter.models["openrouter/auto"] = {"id": "openrouter/auto"}
    with pytest.raises(ProviderError) as exc:
        asyncio.run(adapter.complete("openrouter/auto", MESSAGES))
    assert exc.value.code == "unknown_model"


def test_default_evaluation_override_is_used_and_other_selection_is_unchanged(tmp_path, monkeypatch):
    deepseek = "deepseek/deepseek-v4.1-flash-1017"
    snapshot = tmp_path / "catalog.json"
    snapshot.write_text(json.dumps({"models": [
        {"id": deepseek, "provider_catalog": {"endpoints": [
            {"tag": "first/fp4", "quantization": "fp4", "status": 0},
            {"tag": "deepinfra/fp8", "quantization": "fp8", "status": 0}]}},
        {"id": MODEL, "provider_catalog": {"endpoints": [
            {"tag": "first/fp4", "quantization": "fp4", "status": 0},
            {"tag": TAG, "quantization": "bf16", "status": 0}]}}
    ]}))
    monkeypatch.setattr(provider_module, "SNAPSHOT", snapshot)
    requested_tags = []

    def handler(request):
        assert request.method == "POST"
        requested_tags.append(json.loads(request.content)["provider"]["only"])
        return httpx.Response(200, json=completion(model=deepseek))

    adapter = OpenRouterProvider(api_key=TEST_KEY, transport=httpx.MockTransport(handler))
    assert adapter.pins[deepseek]["tag"] == "deepinfra/fp8"
    assert adapter.pins[MODEL]["tag"] == TAG
    for _ in range(2):
        asyncio.run(adapter.complete(deepseek, MESSAGES))
    assert requested_tags == [["deepinfra/fp8"], ["deepinfra/fp8"]]


@pytest.mark.parametrize("preferred_status", [None, 1])
def test_missing_or_unavailable_default_override_uses_available_snapshot_endpoint(tmp_path, monkeypatch, preferred_status):
    endpoints = [{"tag": "available/fp16", "quantization": "fp16", "status": 0}]
    if preferred_status is not None:
        endpoints.append({"tag": "deepinfra/fp8", "quantization": "fp8", "status": preferred_status})
    deepseek = "deepseek/deepseek-v4.1-flash-1017"
    snapshot = tmp_path / "catalog.json"
    snapshot.write_text(json.dumps({"models": [{"id": deepseek, "provider_catalog": {"endpoints": endpoints}}]}))
    monkeypatch.setattr(provider_module, "SNAPSHOT", snapshot)
    assert OpenRouterProvider(api_key="").pins[deepseek]["tag"] == "available/fp16"


@pytest.mark.parametrize("custom_transport,expected_trust_env", [(True, False), (False, True)])
def test_proxy_environment_is_enabled_only_for_real_transport(monkeypatch, custom_transport, expected_trust_env):
    original_client = httpx.AsyncClient
    flags = []
    mocked_transport = httpx.MockTransport(lambda request: httpx.Response(200, json=completion()))

    def client_factory(**kwargs):
        flags.append(kwargs["trust_env"])
        # The real-transport branch is verified without contacting a network.
        kwargs.update(transport=mocked_transport, trust_env=False)
        return original_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    adapter = provider(lambda request: httpx.Response(200, json=completion()))
    if not custom_transport:
        adapter.transport = None
    assert run_complete(adapter)["status"] == "ready"
    assert flags == [expected_trust_env]
