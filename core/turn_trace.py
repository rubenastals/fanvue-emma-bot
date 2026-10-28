"""Opt-in, in-memory diagnostics for synthetic reply-engine experiments.

Nothing is logged or persisted by this module. A caller that explicitly enables
tracing owns the trace's lifetime and any export of conversation text. Exceptions
are recorded by class only: provider errors can contain credentials or requests.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from core.prompt_layers import BUDGET_CORE, _clip


def inspect_core(persona_text: str, effective_core: Optional[str] = None) -> dict:
    """Measure the actual repository budget without assuming its output is full.

    ``persona_text`` must be the text used for this run, after substitutions.
    When supplied, ``effective_core`` is measured independently and compared with
    the existing clipper. This does not reload a persona or alter any prompt.
    """
    original = persona_text.strip()
    expected = _clip(persona_text, BUDGET_CORE, "CORE")
    effective = expected if effective_core is None else effective_core
    return {
        "persona_input_chars": len(original),
        "core_budget_chars": BUDGET_CORE,
        "core_used_chars": len(effective),
        "truncated": len(original) > BUDGET_CORE,
        "matches_layered_core": effective == expected,
    }


def _value(source: Any, key: str) -> Any:
    return source.get(key) if isinstance(source, Mapping) else getattr(source, key, None)


def completion_usage(usage: Any) -> dict:
    """Only numeric token counts; never serialize an SDK response wholesale."""
    result = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = _value(usage, key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[key] = value
    for parent, key in (
        ("prompt_tokens_details", "cached_tokens"),
        ("completion_tokens_details", "reasoning_tokens"),
    ):
        value = _value(_value(usage, parent), key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            result[key] = value
    return result


@dataclass
class TurnTrace:
    """An optional trace sink. Full request messages require a second opt-in.

    ``persona_diagnostics`` should come from ``inspect_core`` with the exact
    persona used by the caller. Without that evidence, the original size stays
    unknown; only the effective first system message is measured.
    """

    capture_messages: bool = False
    persona_diagnostics: Optional[dict] = None
    events: list[dict] = field(default_factory=list, init=False)

    def record_context(self, messages: Sequence[Mapping[str, str]]) -> None:
        first = messages[0] if messages else {}
        core = first.get("content", "") if first.get("role") == "system" else ""
        sizes = {
            "persona_input_chars": None,
            "core_budget_chars": BUDGET_CORE,
            "core_used_chars": len(core),
            "truncated": core.endswith("?[CORE truncated]"),
            "system_chars": sum(
                len(m.get("content", "")) for m in messages if m.get("role") == "system"
            ),
        }
        if self.persona_diagnostics:
            # Do not copy arbitrary caller fields (or a configuration object).
            for key in ("persona_input_chars", "matches_layered_core"):
                if key in self.persona_diagnostics:
                    sizes[key] = self.persona_diagnostics[key]
        event = {"stage": "context", "message_count": len(messages), "prompt_sizes": sizes}
        if self.capture_messages:
            event["messages"] = [
                {"role": m.get("role", ""), "content": m.get("content", "")}
                for m in messages
            ]
        self.events.append(event)

    def record_completion(
        self,
        *,
        model: str,
        raw: str,
        first_sanitized: str,
        latency_ms: float,
        usage: Any = None,
    ) -> None:
        self.events.append({
            "stage": "completion",
            "call_index": sum(e["stage"] == "completion" for e in self.events),
            "model": model,
            "raw": raw,
            "first_sanitized": first_sanitized,
            "changed": raw != first_sanitized,
            "latency_ms": round(latency_ms, 3),
            "usage": completion_usage(usage),
        })

    def record_final(self, text: str) -> None:
        self.events.append({"stage": "final", "text": text})

    def record_error(self, stage: str, error: Exception) -> None:
        self.events.append({"stage": "error", "failed_stage": stage, "error_type": type(error).__name__})

    def as_dict(self) -> dict:
        return {"schema_version": 1, "events": deepcopy(self.events)}
