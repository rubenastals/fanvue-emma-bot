"""Bounded private prompt A/B evaluation; no training and no live-chat client."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

from lab.chat_dataset import DatasetError, no_symlinks
from lab.real_chat_analysis import AnalysisError, _request_json, validate_output_path, write_private_json

ROOT = Path(__file__).resolve().parents[1]
MODEL = "deepseek/deepseek-v4.1-flash-1017"
PROVIDER = "deepinfra/fp8"
MAX_PRICE = {"prompt": 1, "completion": 5, "request": 0}
MAX_COMPLETION_TOKENS = 1024
MAX_CASES = 9
ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
SCOPE = "isolated_persona_prompt_layer"
LIMITATION = "Only persona plus visible messages are evaluated; lab.policy.build_context, commercial memory, the poller and end-to-end bot behavior are outside this experiment."


class EvaluationError(Exception):
    pass


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def number(value):
    try:
        return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
    except (OverflowError, ValueError):
        return None


def read_bytes(path: Path, limit: int) -> bytes:
    no_symlinks(path)
    with path.open("rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise EvaluationError("invalid_file")
        raw = handle.read(limit + 1)
    if len(raw) > limit:
        raise EvaluationError("input_too_large")
    return raw


def json_object(raw) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise EvaluationError("duplicate_json_key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    if not isinstance(value, dict):
        raise EvaluationError("invalid_json_object")
    return value


def clean_messages(messages) -> list[dict]:
    if not isinstance(messages, list) or not 1 <= len(messages) <= 32:
        raise EvaluationError("invalid_case")
    selected = []
    for message in messages:
        if (not isinstance(message, dict) or message.get("role") not in ("user", "assistant")
                or not isinstance(message.get("content"), str) or not message["content"].strip()
                or len(message["content"].encode()) > 8192):
            raise EvaluationError("invalid_message")
        # Reference answers, rubrics, source IDs and arbitrary fields never enter prompts.
        selected.append({"role": message["role"], "content": message["content"]})
    if selected[-1]["role"] != "user":
        raise EvaluationError("last_message_must_be_user")
    return selected


def read_cases(path: Path, review_path: Path) -> tuple[list[dict], dict]:
    raw = read_bytes(path, 128 * 1024)
    review_bytes = read_bytes(review_path, 16 * 1024)
    review = json_object(review_bytes)
    if (review.get("schemaVersion") != "fanvue.behavior-evaluation-review.v1"
            or review.get("inputBytesSha256") != digest(raw)
            or review.get("approvedNonExplicitInputs") is not True
            or review.get("purpose") != "offline_response_evaluation"
            or review.get("classification") != "development_regression"
            or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip()):
        raise EvaluationError("invalid_review")
    rows = [json_object(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not 1 <= len(rows) <= MAX_CASES:
        raise EvaluationError("invalid_case_count")
    clean = []
    for row in rows:
        cid, messages = row.get("id"), row.get("inputMessages")
        if not isinstance(cid, str) or not ID.fullmatch(cid):
            raise EvaluationError("invalid_case")
        clean.append({"id": cid, "messages": clean_messages(messages)})
    ids = [case["id"] for case in clean]
    if len(set(ids)) != len(ids) or review.get("caseIds") != ids:
        raise EvaluationError("review_case_mismatch")
    return clean, {"inputBytesSha256": digest(raw), "reviewBytesSha256": digest(review_bytes),
                   "classification": "development_regression", "caseIds": ids}


def ceiling(request: dict) -> float:
    # Conservative input-byte estimate plus overhead, not an invoice guarantee.
    bound = sum(len(m["content"].encode()) for m in request["messages"]) + 4096
    return round((bound * MAX_PRICE["prompt"] + MAX_COMPLETION_TOKENS * MAX_PRICE["completion"]) / 1_000_000, 6)


def build_plan(cases: list[dict], base_prompt: str, rules: str, budget: float) -> dict:
    if not isinstance(cases, list) or not 1 <= len(cases) <= MAX_CASES:
        raise EvaluationError("invalid_case_count")
    clean, ids = [], set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str) or not ID.fullmatch(case["id"]):
            raise EvaluationError("invalid_case")
        if case["id"] in ids:
            raise EvaluationError("duplicate_case_id")
        ids.add(case["id"])
        clean.append({"id": case["id"], "messages": clean_messages(case.get("messages"))})
    cases = clean
    if not base_prompt.strip() or not rules.strip() or len(base_prompt.encode()) > 16384 or len(rules.encode()) > 16384:
        raise EvaluationError("invalid_prompt")
    if type(budget) not in (int, float) or not math.isfinite(budget) or not 0 < budget <= 0.50:
        raise EvaluationError("invalid_budget")
    variants = {"baseline": base_prompt.strip(), "rules_v2": base_prompt.strip() + "\n\n" + rules.strip()}
    requests = []
    for index, case in enumerate(cases):
        # Balance which variant goes first; all settings except the prompt match.
        order = ["baseline", "rules_v2"] if index % 2 == 0 else ["rules_v2", "baseline"]
        for variant in order:
            payload = {"model": MODEL, "stream": False, "max_completion_tokens": MAX_COMPLETION_TOKENS,
                       "reasoning": {"effort": "low", "exclude": True},
                       "messages": [{"role": "system", "content": variants[variant]}] + case["messages"],
                       "provider": {"only": [PROVIDER], "allow_fallbacks": False, "require_parameters": True,
                                    "data_collection": "deny", "zdr": True, "max_price": dict(MAX_PRICE)}}
            requests.append({"caseId": case["id"], "variant": variant, "payload": payload})
    estimate = round(sum(ceiling(r["payload"]) for r in requests), 6)
    if estimate > budget:
        raise EvaluationError("estimated_budget_exceeded")
    return {"requests": requests, "variants": variants, "estimatedCostCeilingUsd": estimate,
            "budgetUsd": budget, "scope": SCOPE}


def validate_plan(plan: dict):
    """Reject edited settings, duplicate dispatches or unbalanced inputs before calls."""
    try:
        baseline, candidate = plan["variants"]["baseline"], plan["variants"]["rules_v2"]
        prefix = baseline + "\n\n"
        if not candidate.startswith(prefix):
            raise EvaluationError("invalid_plan")
        cases = [{"id": item["caseId"], "messages": item["payload"]["messages"][1:]}
                 for item in plan["requests"] if item["variant"] == "baseline"]
        expected = build_plan(cases, baseline, candidate[len(prefix):], plan["budgetUsd"])
        if plan != expected:
            raise EvaluationError("invalid_plan")
    except (KeyError, IndexError, TypeError, AttributeError):
        raise EvaluationError("invalid_plan") from None


def validate_output(output: Path) -> Path:
    output = output.expanduser().absolute()
    no_symlinks(output)
    if output.exists():
        raise EvaluationError("output_exists")
    validate_output_path(output / "plan.json")
    return output


def create_output(output: Path):
    missing, current = [], output.parent
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
    output.mkdir(mode=0o700)  # Exclusive creation is the run's lock; no implicit resume.


def response_record(data: dict) -> dict:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    result = {"costUsd": number(usage.get("cost")), "inputTokens": number(usage.get("prompt_tokens")),
              "outputTokens": number(usage.get("completion_tokens")), "status": "error"}
    choices = data.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    if not isinstance(choice, dict):
        choice = {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    text = message.get("content")
    if (data.get("error") or data.get("status") in ("error", "failed", "incomplete") or choice.get("error")
            or choice.get("finish_reason") != "stop" or message.get("refusal") or message.get("tool_calls")
            or message.get("function_call") or not isinstance(text, str) or not text.strip()):
        result["errorCode"] = "incomplete_or_rejected"
        return result
    result.update(status="unreviewed_response", text=text.strip(), finishReason="stop")
    # Preserve reported identity separately from requested routing.
    for source, target in (("model", "returnedModel"), ("provider", "reportedProvider"), ("id", "responseId")):
        value = data.get(source)
        result[target] = value[:200] if isinstance(value, str) else None
    return result


async def run(plan: dict, provenance: dict, output: Path, api_key: str, transport=None) -> dict:
    validate_plan(plan)
    output = validate_output(output)
    if not isinstance(api_key, str) or not api_key.strip():
        raise EvaluationError("missing_key")
    create_output(output)
    manifest = {"schemaVersion": "fanvue.behavior-evaluation-result.v1", "createdAt": datetime.now(timezone.utc).isoformat(),
                "purpose": "offline_response_evaluation", "classification": "development_regression",
                "scope": SCOPE, "limitations": [LIMITATION],
                "trainingJobStarted": False, "fanMessagesSent": 0, "model": MODEL, "requestedProvider": PROVIDER,
                "provenance": provenance, "budgetUsd": plan["budgetUsd"],
                "estimatedCostCeilingUsd": plan["estimatedCostCeilingUsd"], "plannedRequests": len(plan["requests"]),
                "variants": {name: {"sha256": digest(prompt.encode()), "prompt": prompt} for name, prompt in plan["variants"].items()},
                "requestSettings": {k: v for k, v in plan["requests"][0]["payload"].items() if k != "messages"}}
    # Persist the immutable run plan before any paid request. One record is saved
    # after each call. A partial directory without summary is not a completed run.
    write_private_json(output / "plan.json", manifest)
    headers = {"Authorization": "Bearer " + api_key, "Content-Type": "application/json",
               "X-OpenRouter-Cache": "false", "X-OpenRouter-Metadata": "enabled",
               "X-OpenRouter-Title": "Fanv Private Behavior Evaluation"}
    records, spent, stop_reason = [], 0.0, None
    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15), follow_redirects=False,
                                 trust_env=True, transport=transport) as client:
        for index, item in enumerate(plan["requests"], 1):
            if spent + ceiling(item["payload"]) > plan["budgetUsd"]:
                stop_reason = "budget_limit"
                break
            request_sha = digest(json.dumps(item["payload"], ensure_ascii=False, sort_keys=True,
                                            separators=(",", ":"), allow_nan=False).encode())
            # An unresolved dispatch marker means outcome/cost are unknown, not
            # permission to resend. Persist it before starting the paid request.
            write_private_json(output / f"request_{index:03d}.json", {
                "caseId": item["caseId"], "variant": item["variant"], "status": "dispatching",
                "createdAt": datetime.now(timezone.utc).isoformat(), "requestPayloadSha256": request_sha,
                "estimatedCostCeilingUsd": ceiling(item["payload"]), "responseRecordRequired": True})
            start = time.perf_counter()
            record = {"caseId": item["caseId"], "variant": item["variant"], "status": "error", "costUsd": None,
                      "requestPayloadSha256": request_sha}
            try:
                data = await asyncio.wait_for(_request_json(client, headers, item["payload"]), 45)
                record.update(response_record(data))
            except AnalysisError as exc:
                record["errorCode"] = exc.code
            except (httpx.TimeoutException, asyncio.TimeoutError):
                record["errorCode"] = "timeout"
            except httpx.HTTPError:
                record["errorCode"] = "connection_error"
            except (ValueError, TypeError, KeyError, IndexError, RecursionError):
                record["errorCode"] = "invalid_response"
            record["latencyMs"] = round((time.perf_counter() - start) * 1000)
            write_private_json(output / f"response_{index:03d}.json", record)
            records.append(record)
            if record["costUsd"] is not None:
                spent += record["costUsd"]
            print(json.dumps({"request": index, "caseId": record["caseId"], "variant": record["variant"],
                              "status": record["status"], "costUsd": record["costUsd"],
                              "errorCode": record.get("errorCode")}), flush=True)
            if record["costUsd"] is None or record["status"] == "error":
                stop_reason = "unknown_cost_or_error"
                break
            if spent > plan["budgetUsd"]:
                stop_reason = "reported_budget_exceeded"
                break
    summary = {"requestsMade": len(records), "plannedRequests": len(plan["requests"]),
               "scope": SCOPE, "limitations": [LIMITATION],
               "reportedCostUsd": round(spent, 8), "missingCostCount": sum(r["costUsd"] is None for r in records),
               "unreviewedResponses": sum(r["status"] == "unreviewed_response" for r in records),
               "complete": len(records) == len(plan["requests"]) and stop_reason is None, "stopReason": stop_reason,
               "qualityScoresAssigned": False, "trainingJobStarted": False}
    write_private_json(output / "summary.json", summary)
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--base-prompt", type=Path, default=ROOT / "lab/fixtures/persona.md")
    parser.add_argument("--rules", type=Path, default=ROOT / "lab/fixtures/behavior_rules_v2.md")
    parser.add_argument("--budget-usd", type=float, default=0.50)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.lab")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args(argv)
    try:
        cases, provenance = read_cases(args.cases, args.review)
        plan = build_plan(cases, args.base_prompt.read_text(), args.rules.read_text(), args.budget_usd)
        if not args.live:
            print(json.dumps({"status": "dry_run", "requests": len(plan["requests"]),
                              "scope": SCOPE, "limitations": [LIMITATION],
                              "estimatedCostCeilingUsd": plan["estimatedCostCeilingUsd"], "trainingJobStarted": False}))
            return 0
        if not args.output_dir:
            raise EvaluationError("output_required")
        # Resolve and validate the output before reading provider configuration.
        validate_output(args.output_dir)
        load_dotenv(args.env_file, override=False)
        result = asyncio.run(run(plan, provenance, args.output_dir, os.getenv("OPENROUTER_API_KEY", "")))
        print(json.dumps(result))
        return 0 if result["complete"] else 2
    except (EvaluationError, OSError, ValueError, TypeError, AnalysisError, DatasetError) as exc:
        code = str(exc) if isinstance(exc, EvaluationError) else "input_or_output_error"
        print(json.dumps({"status": "error", "code": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
