"""OpenRouter adapter with an explicit model and pinned upstream; no automatic retries."""
from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import httpx

API = "https://openrouter.ai/api/v1"
SNAPSHOT = Path(__file__).with_name("openrouter_catalog_snapshot.json")
# Keep the initial DeepSeek comparison on an explicit FP8 backend rather than
# inheriting the catalogue's first (currently FP4) endpoint. This is not a rank.
DEFAULT_EVALUATION_ENDPOINTS = {
    "deepseek/deepseek-v4.1-flash-1017": "deepinfra/fp8",
}


class ProviderError(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def selected_endpoint(endpoints: list[dict]) -> dict | None:
    available = [e for e in endpoints if isinstance(e, dict) and isinstance(e.get("tag"), str) and e["tag"] and e.get("status", 0) == 0]
    # Prefer native precision where known, then retain API ordering. This is not a quality score.
    return next((e for e in available if e.get("quantization") in ("fp16", "bf16", "fp32")), available[0] if available else None)


def _mapping(value) -> dict:
    return value if isinstance(value, dict) else {}


def _number(value) -> int | float | None:
    # Zero usage/cost is meaningful; missing, boolean, or invalid values are not zero.
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value >= 0 and (not isinstance(value, float) or math.isfinite(value)):
            return value
    return None


def _reported_text(value, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) and value.strip() else None


def _actual_provider(metadata: dict) -> str:
    available = _mapping(metadata.get("endpoints")).get("available")
    if not isinstance(available, list):
        return "unreported"
    selected = {
        value for endpoint in available if isinstance(endpoint, dict) and endpoint.get("selected") is True
        if (value := _reported_text(endpoint.get("provider"), 120)) is not None
    }
    # A requested pin is not evidence that an upstream actually served the response.
    return selected.pop() if len(selected) == 1 else "unreported"


class OpenRouterProvider:
    def __init__(self, api_key: str | None = None, transport=None):
        self._key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        self.transport = transport
        saved = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.exists() else {"models": [], "fetched_at": None}
        self.models = {m["id"]: m for m in saved["models"]}
        self.fetched_at = saved.get("fetched_at")
        self.pins = {}
        self._explicit_pins: dict[tuple[str, str], dict] = {}
        for model in saved["models"]:
            endpoints = model.get("provider_catalog", {}).get("endpoints", [])
            preferred_tag = DEFAULT_EVALUATION_ENDPOINTS.get(model["id"])
            endpoint = next((e for e in endpoints if isinstance(e, dict) and preferred_tag
                             and e.get("tag") == preferred_tag and e.get("status", 0) == 0), None)
            endpoint = endpoint or selected_endpoint(endpoints)
            if endpoint:
                self.pins[model["id"]] = endpoint

    @property
    def configured(self) -> bool:
        return bool(self._key.strip())

    def public_models(self) -> list[dict]:
        return [{"id": m["id"], "label": m.get("name", m["id"]), "context_length": m.get("context_length"),
                 "pricing": m.get("pricing"), "provider_tag": self.pins.get(m["id"], {}).get("tag"),
                 "quantization": self.pins.get(m["id"], {}).get("quantization"),
                 "supported_parameters": m.get("supported_parameters", [])} for m in self.models.values()]

    async def refresh_models(self) -> list[dict]:
        data = await self._request("GET", "/models", authenticated=False)
        if not isinstance(data.get("data"), list):
            raise ProviderError("invalid_catalog", "El proveedor devolvió un catálogo no válido.")
        for model in data["data"]:
            if not isinstance(model, dict) or not isinstance(model.get("id"), str):
                continue
            modalities = _mapping(model.get("architecture")).get("output_modalities", ["text"])
            if isinstance(modalities, list) and "text" in modalities and re.fullmatch(r"[\w.:-]+/[\w.:-]+", model["id"]):
                self.models[model["id"]] = model
        self.fetched_at = datetime.now(timezone.utc).isoformat()
        return self.public_models()

    async def _request(self, method: str, path: str, payload=None, authenticated=True) -> dict:
        headers = {"Content-Type": "application/json", "X-OpenRouter-Title": "Fanv Conversation Lab", "X-OpenRouter-Metadata": "enabled"}
        if authenticated:
            if not self.configured:
                raise ProviderError("missing_key", "Configura OPENROUTER_API_KEY en el servidor del laboratorio.")
            headers["Authorization"] = f"Bearer {self._key}"
        try:
            async with httpx.AsyncClient(timeout=70, transport=self.transport, follow_redirects=False,
                                         trust_env=self.transport is None) as client:
                response = await client.request(method, API + path, headers=headers, json=payload)
        except httpx.TimeoutException:
            raise ProviderError("timeout", "El proveedor agotó el tiempo de espera. No se ha reintentado.") from None
        except httpx.HTTPError:
            raise ProviderError("connection_error", "No se pudo conectar con OpenRouter.") from None
        if not 200 <= response.status_code < 300:
            known = {401: "Clave de OpenRouter no válida.", 402: "Saldo o presupuesto de OpenRouter insuficiente.",
                     404: "Modelo o proveedor fijado no disponible para esta cuenta.", 429: "Límite de solicitudes alcanzado."}
            raise ProviderError(f"http_{response.status_code}", known.get(response.status_code, f"OpenRouter devolvió HTTP {response.status_code}. No se ha reintentado."))
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError()
        except (ValueError, TypeError):
            raise ProviderError("invalid_response", "Respuesta JSON no válida del proveedor.") from None
        if data.get("error") is not None or data.get("status") in ("error", "failed"):
            raise ProviderError("provider_error", "OpenRouter informó de un error de generación. No se usó otro modelo.")
        return data

    async def complete(self, model: str, messages: list[dict], provider_tag: str | None = None) -> dict:
        if not self.configured:
            raise ProviderError("missing_key", "Configura OPENROUTER_API_KEY en el servidor del laboratorio.")
        if model not in self.models or model.startswith("openrouter/"):
            raise ProviderError("unknown_model", "Selecciona un modelo concreto del catálogo; actualiza la lista si es necesario.")
        existing_pin = self.pins.get(model)
        explicit_pin = self._explicit_pins.get((model, provider_tag)) if provider_tag else None
        if existing_pin and (not provider_tag or existing_pin.get("tag") == provider_tag):
            endpoint = existing_pin
        elif explicit_pin:
            endpoint = explicit_pin
        else:
            author, slug = model.split("/", 1)
            data = await self._request("GET", f"/models/{quote(author, safe='')}/{quote(slug, safe='')}/endpoints", authenticated=False)
            endpoints = _mapping(data.get("data")).get("endpoints", [])
            if not isinstance(endpoints, list):
                raise ProviderError("invalid_catalog", "El proveedor devolvió una lista de endpoints no válida.")
            endpoint = next((e for e in endpoints if isinstance(e, dict) and e.get("tag") == provider_tag and e.get("status", 0) == 0), None) if provider_tag else selected_endpoint(endpoints)
            if not endpoint:
                raise ProviderError("no_endpoint", "No se encontró el proveedor solicitado para este modelo.")
            # A previously selected endpoint stays pinned across runs; failures never repin it.
            if provider_tag:
                self._explicit_pins[(model, provider_tag)] = endpoint
            else:
                self.pins[model] = endpoint
        tag = endpoint["tag"]
        payload = {"model": model, "messages": messages, "stream": False, "max_completion_tokens": 1024,
                   "provider": {"order": [tag], "only": [tag], "allow_fallbacks": False,
                                "require_parameters": True, "data_collection": "deny"}}
        supported = endpoint.get("supported_parameters", self.models[model].get("supported_parameters", []))
        if not isinstance(supported, list):
            supported = []
        if "reasoning" in supported:
            payload["reasoning"] = {"effort": "low", "exclude": True}
        start = time.perf_counter()
        data = await self._request("POST", "/chat/completions", payload)
        latency = round((time.perf_counter() - start) * 1000)
        try:
            choice = data["choices"][0]
            if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                raise ValueError()
            message = choice["message"]
            finish = _reported_text(choice.get("finish_reason"), 80)
            if choice.get("error") is not None or finish == "error":
                raise ProviderError("provider_error", "El proveedor informó de un fallo durante la generación. No se usó otro modelo.")
            if message.get("refusal") or finish in ("content_filter", "refusal", "safety"):
                raise ProviderError("refused", "El proveedor rechazó esta solicitud. No se usó otro modelo.")
            text = message.get("content")
            if not isinstance(text, str) or not text.strip():
                raise ValueError()
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("empty_response", "El modelo no devolvió texto visible. Revisa el límite de salida y su modo de razonamiento.") from None
        usage = _mapping(data.get("usage"))
        prompt_details = _mapping(usage.get("prompt_tokens_details"))
        completion_details = _mapping(usage.get("completion_tokens_details"))
        metrics = {"latency_ms": latency, "input_tokens": _number(usage.get("prompt_tokens")),
                   "output_tokens": _number(usage.get("completion_tokens")), "total_tokens": _number(usage.get("total_tokens")),
                   "cost_usd": _number(usage.get("cost")),
                   "reasoning_tokens": _number(completion_details.get("reasoning_tokens")),
                   "cached_input_tokens": _number(prompt_details.get("cached_tokens")),
                   "cache_write_tokens": _number(prompt_details.get("cache_write_tokens"))}
        metadata = _mapping(data.get("openrouter_metadata"))
        status = "ready" if finish == "stop" and data.get("status") != "incomplete" else "incomplete"
        return {"text": text, "status": status, "metrics": metrics,
                "returned_model": _reported_text(data.get("model"), 200),
                "response_id": _reported_text(data.get("id"), 200), "upstream_provider": _actual_provider(metadata),
                "requested_provider_tag": tag, "quantization": endpoint.get("quantization"), "finish_reason": finish,
                "request_settings": {k: v for k, v in payload.items() if k != "messages"},
                "routing_metadata": metadata or None}
