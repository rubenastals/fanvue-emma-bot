"""Synthetic seam tests: tracing observes replies without changing behavior."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core import reply_engine
from core.prompt_layers import BUDGET_CORE, build_system_layers
from core.turn_trace import TurnTrace, completion_usage, inspect_core


@pytest.fixture
def assembled():
    return SimpleNamespace(
        messages=[{"role": "system", "content": "Synthetic persona"},
                  {"role": "user", "content": "¿Qué tal va tu día?"}],
        offer=None,
        want_spanish=True,
        usable_name="Dani",
        name_confirmed=True,
        name_max_uses=1,
        ghost_free_ban=False,
        voice_will_send=False,
    )


def fake_client(monkeypatch, *, content="  Buen día 🙂  ", failure=None):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=42, completion_tokens=8, total_tokens=50),
    )
    create = Mock(return_value=response, side_effect=failure)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(reply_engine, "_client", lambda: client)
    return create


def test_tracing_keeps_exact_provider_request_and_response(monkeypatch, assembled):
    create = fake_client(monkeypatch)
    sanitize = Mock(side_effect=lambda text, **kwargs: text.replace(" 🙂", ""))
    monkeypatch.setattr(reply_engine, "_sanitize_reply", sanitize)

    ordinary = reply_engine._call_creative(assembled, assembled.messages)
    ordinary_request = create.call_args.kwargs.copy()
    trace = TurnTrace()
    traced = reply_engine._call_creative(assembled, assembled.messages, trace=trace)

    assert ordinary == traced == "Buen día"
    assert create.call_count == 2  # tracing does not add a model call
    assert create.call_args.kwargs == ordinary_request
    assert sanitize.call_count == 2
    completion = trace.events[0]
    assert completion["raw"] == "  Buen día 🙂  "  # before whitespace cleanup
    assert completion["first_sanitized"] == "Buen día"
    assert completion["changed"] is True
    assert completion["usage"] == {"prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50}
    assert completion["latency_ms"] >= 0
    assert set(ordinary_request) <= {
        "model", "messages", "temperature", "top_p", "frequency_penalty",
        "presence_penalty", "max_tokens", "extra_body",
    }


def test_trace_records_rewrite_calls_and_final_separately(monkeypatch, assembled):
    create = fake_client(monkeypatch, content="Hola, Dani.")
    monkeypatch.setattr(reply_engine, "_sanitize_reply", lambda text, **kwargs: text)
    monkeypatch.setattr(reply_engine, "assemble_emma_turn", lambda *args, **kwargs: assembled)
    decision = object()

    def post_draft(text, turn, *, call):
        assert text == "Hola, Dani."
        call(turn.messages + [{"role": "user", "content": "Más breve."}])
        return "Hola.", decision

    monkeypatch.setattr(reply_engine, "apply_post_draft", post_draft)
    trace = TurnTrace(capture_messages=True)
    assert reply_engine.generate_emma_reply("Hola", trace=trace) == ("Hola.", decision)
    assert [e["stage"] for e in trace.events] == ["context", "completion", "completion", "final"]
    assert [e["call_index"] for e in trace.events if e["stage"] == "completion"] == [0, 1]
    assert create.call_count == 2
    assert trace.events[0]["messages"] == assembled.messages
    assert trace.events[-1]["text"] == "Hola."


def test_no_trace_keeps_two_argument_creative_call(monkeypatch, assembled):
    monkeypatch.setattr(reply_engine, "assemble_emma_turn", lambda *args, **kwargs: assembled)
    calls = []

    def old_style_creative(turn, messages):
        calls.append((turn, messages))
        return "Hola."

    monkeypatch.setattr(reply_engine, "_call_creative", old_style_creative)
    monkeypatch.setattr(reply_engine, "apply_post_draft", lambda text, turn, **kwargs: (text, None))
    assert reply_engine.generate_emma_reply("Hola") == ("Hola.", None)
    assert calls == [(assembled, assembled.messages)]


def test_provider_failure_is_propagated_without_secret_or_fallback(monkeypatch, assembled):
    failure = RuntimeError("Bearer top-secret: diagnostic request body")
    create = fake_client(monkeypatch, failure=failure)
    sanitize = Mock()
    monkeypatch.setattr(reply_engine, "_sanitize_reply", sanitize)
    trace = TurnTrace()
    with pytest.raises(RuntimeError) as caught:
        reply_engine._call_creative(assembled, assembled.messages, trace=trace)
    assert caught.value is failure
    assert create.call_count == 1
    sanitize.assert_not_called()
    assert trace.events == [{"stage": "error", "failed_stage": "provider", "error_type": "RuntimeError"}]
    assert "top-secret" not in str(trace.as_dict())


def test_context_text_requires_explicit_opt_in_and_export_is_independent(assembled):
    trace = TurnTrace()
    trace.record_context(assembled.messages)
    assert "messages" not in trace.events[0]
    assert trace.events[0]["prompt_sizes"]["persona_input_chars"] is None

    full = TurnTrace(capture_messages=True)
    full.record_context(assembled.messages)
    assembled.messages[0]["content"] = "changed after capture"
    assert full.events[0]["messages"][0]["content"] == "Synthetic persona"
    exported = full.as_dict()
    exported["events"][0]["messages"].clear()
    assert full.events[0]["messages"]


def test_core_measurement_uses_real_clipper_and_unicode_character_count():
    persona = "  " + "🙂" * (BUDGET_CORE + 1) + "  "
    messages, sizes = build_system_layers(core_prompt=persona)
    measured = inspect_core(persona, messages[0]["content"])
    assert measured["persona_input_chars"] == BUDGET_CORE + 1
    assert measured["core_used_chars"] == sizes["core"]
    assert measured["core_used_chars"] < BUDGET_CORE
    assert measured["truncated"] is True
    assert measured["matches_layered_core"] is True
    trace = TurnTrace(persona_diagnostics=measured)
    trace.record_context(messages)
    assert trace.events[0]["prompt_sizes"]["persona_input_chars"] == BUDGET_CORE + 1
    assert trace.events[0]["prompt_sizes"]["truncated"] is True
    assert inspect_core("Exact fit" * 2)["truncated"] is False
    assert inspect_core(persona, "different effective core")["matches_layered_core"] is False


def test_usage_only_copies_allowlisted_numeric_fields():
    usage = {
        "prompt_tokens": 20,
        "completion_tokens": 5,
        "total_tokens": 25,
        "api_key": "secret",
        "headers": {"Authorization": "Bearer secret"},
        "prompt_tokens_details": {"cached_tokens": 10, "other": "secret"},
        "completion_tokens_details": {"reasoning_tokens": 3},
    }
    assert completion_usage(usage) == {
        "prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25,
        "cached_tokens": 10, "reasoning_tokens": 3,
    }
    assert completion_usage(None) == {}
    assert completion_usage({"prompt_tokens": -1, "completion_tokens": True, "total_tokens": "secret"}) == {}
