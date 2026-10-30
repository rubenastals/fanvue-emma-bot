"""Private prompt evaluation: synthetic inputs, mocked HTTP, no keys or real data."""
import asyncio
import contextlib
import copy
import io
import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from lab import behavior_eval as module


def response(cost=0.001, finish="stop"):
    usage = {"prompt_tokens": 20, "completion_tokens": 10}
    if cost is not None:
        usage["cost"] = cost
    return {"choices": [{"finish_reason": finish, "message": {"content": "A neutral synthetic reply."}}],
            "usage": usage, "model": module.MODEL, "provider": "DeepInfra", "id": "synthetic-response"}


class BehaviorEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.cases_path = self.base / "cases.jsonl"
        self.review_path = self.base / "review.json"
        self.rows = [
            {"id": "case_one", "inputMessages": [{"role": "user", "content": "Please change the topic.",
                                                    "rubric": "MESSAGE_RUBRIC_SENTINEL"}],
             "referenceResponse": {"content": "REFERENCE_SENTINEL"}, "rubric": "RUBRIC_SENTINEL",
             "sourceRefs": "PRIVATE_SOURCE_SENTINEL"},
            {"id": "case_two", "inputMessages": [{"role": "assistant", "content": "Hello."},
                                                    {"role": "user", "content": "We already said hello."}],
             "referenceResponse": "SECOND_REFERENCE_SENTINEL"},
        ]
        raw = b"".join(json.dumps(row).encode() + b"\n" for row in self.rows)
        self.cases_path.write_bytes(raw)
        self.review = {"schemaVersion": "fanvue.behavior-evaluation-review.v1",
                       "inputBytesSha256": module.digest(raw), "approvedNonExplicitInputs": True,
                       "purpose": "offline_response_evaluation", "classification": "development_regression",
                       "reviewer": "synthetic-reviewer", "caseIds": [r["id"] for r in self.rows]}
        self.review_path.write_text(json.dumps(self.review))
        self.cases, self.provenance = module.read_cases(self.cases_path, self.review_path)
        self.plan = module.build_plan(self.cases, "A fictional adult persona.", "Respect stated boundaries.", 0.50)
        self.calls = []

    def execute(self, handler=None, plan=None, output=None):
        def wrapped(request):
            self.calls.append(request)
            return handler(request) if handler else httpx.Response(200, json=response())
        with contextlib.redirect_stdout(io.StringIO()):
            return asyncio.run(module.run(plan or self.plan, self.provenance, output or self.base / "output",
                                          "synthetic-not-a-real-key", transport=httpx.MockTransport(wrapped)))

    def test_reference_rubrics_and_metadata_never_enter_requests(self):
        encoded = json.dumps(self.plan)
        for sentinel in ("REFERENCE_SENTINEL", "RUBRIC_SENTINEL", "PRIVATE_SOURCE_SENTINEL"):
            self.assertNotIn(sentinel, encoded)
        dirty_cases = copy.deepcopy(self.cases)
        dirty_cases[0]["messages"][0]["referenceResponse"] = "DIRECT_REFERENCE_SENTINEL"
        direct = module.build_plan(dirty_cases, "Persona", "Rules", 0.50)
        self.assertNotIn("DIRECT_REFERENCE_SENTINEL", json.dumps(direct))
        self.execute()
        for request in self.calls:
            self.assertNotIn("SENTINEL", request.content.decode())

    def test_hashes_use_the_same_once_read_review_and_input_bytes(self):
        review_bytes = self.review_path.read_bytes()
        with patch.object(module, "read_bytes", wraps=module.read_bytes) as reader:
            _, provenance = module.read_cases(self.cases_path, self.review_path)
        review_reads = [call for call in reader.call_args_list if call.args[0] == self.review_path]
        self.assertEqual(len(review_reads), 1)
        self.assertEqual(provenance["reviewBytesSha256"], module.digest(review_bytes))
        self.cases_path.write_bytes(self.cases_path.read_bytes() + b"\n")
        with self.assertRaisesRegex(module.EvaluationError, "invalid_review"):
            module.read_cases(self.cases_path, self.review_path)

    def test_review_approval_and_case_order_must_match(self):
        for field, value, error in [("approvedNonExplicitInputs", False, "invalid_review"),
                                     ("caseIds", ["case_two", "case_one"], "review_case_mismatch"),
                                     ("classification", "heldout", "invalid_review")]:
            with self.subTest(field=field):
                changed = {**self.review, field: value}
                self.review_path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(module.EvaluationError, error):
                    module.read_cases(self.cases_path, self.review_path)

    def test_bounded_plan_balanced_variants_and_fixed_routing(self):
        cases = [{"id": f"synthetic_{i}", "messages": self.cases[0]["messages"]} for i in range(9)]
        plan = module.build_plan(cases, "Persona", "Rules", 0.50)
        self.assertEqual(len(plan["requests"]), 18)
        self.assertLessEqual(plan["estimatedCostCeilingUsd"], 0.50)
        self.assertEqual([r["variant"] for r in plan["requests"][:4]], ["baseline", "rules_v2", "rules_v2", "baseline"])
        for item in plan["requests"]:
            payload = item["payload"]
            self.assertEqual(payload["model"], module.MODEL)
            self.assertEqual(payload["max_completion_tokens"], 1024)
            self.assertEqual(payload["reasoning"], {"effort": "low", "exclude": True})
            self.assertEqual(payload["provider"], {"only": ["deepinfra/fp8"], "allow_fallbacks": False,
                             "require_parameters": True, "data_collection": "deny", "zdr": True,
                             "max_price": {"prompt": 1, "completion": 5, "request": 0}})
        with self.assertRaisesRegex(module.EvaluationError, "invalid_case_count"):
            module.build_plan(cases + [{"id": "tenth", "messages": self.cases[0]["messages"]}], "Persona", "Rules", 0.50)
        with self.assertRaisesRegex(module.EvaluationError, "estimated_budget_exceeded"):
            module.build_plan(self.cases, "Persona", "Rules", 0.001)

    def test_duplicate_dispatch_or_modified_settings_fail_before_client(self):
        for mutate in (lambda p: p["requests"].append(copy.deepcopy(p["requests"][0])),
                       lambda p: p["requests"][0]["payload"]["provider"].update(allow_fallbacks=True)):
            with self.subTest(mutate=mutate):
                plan = copy.deepcopy(self.plan)
                mutate(plan)
                with patch.object(module.httpx, "AsyncClient", side_effect=AssertionError("must not construct client")):
                    with self.assertRaises(module.EvaluationError):
                        self.execute(plan=plan)
        self.assertFalse((self.base / "output").exists())

    def test_output_rejected_before_client_or_configuration(self):
        existing = self.base / "existing"
        existing.mkdir()
        for output in (existing, module.ROOT / "docs" / "never-create-evaluation"):
            with self.subTest(output=output):
                with patch.object(module.httpx, "AsyncClient", side_effect=AssertionError("must not construct client")):
                    with self.assertRaises((module.EvaluationError, module.AnalysisError)):
                        self.execute(output=output)
        persona, rules = self.base / "persona.md", self.base / "rules.md"
        persona.write_text("Synthetic persona")
        rules.write_text("Synthetic rules")
        with patch.object(module, "load_dotenv", side_effect=AssertionError("must not read configuration")), \
                contextlib.redirect_stdout(io.StringIO()):
            result = module.main(["--cases", str(self.cases_path), "--review", str(self.review_path),
                                  "--base-prompt", str(persona), "--rules", str(rules), "--live",
                                  "--output-dir", str(existing)])
        self.assertEqual(result, 2)

    def test_unknown_cost_and_provider_errors_stop_without_retry(self):
        fixtures = [httpx.Response(200, json=response(cost=None)),
                    httpx.Response(200, json=response(cost="0.01")),
                    httpx.Response(200, json=response(cost=0.002, finish="length")),
                    httpx.Response(503, text="PRIVATE_ERROR_SENTINEL")]
        for i, fixture in enumerate(fixtures):
            with self.subTest(i=i):
                self.calls = []
                output = self.base / f"stopped_{i}"
                summary = self.execute(lambda _: fixture, output=output)
                self.assertEqual(len(self.calls), 1)
                self.assertFalse(summary["complete"])
                self.assertEqual(summary["stopReason"], "unknown_cost_or_error")
                record = json.loads((output / "response_001.json").read_bytes())
                self.assertNotIn("PRIVATE_ERROR_SENTINEL", json.dumps(record))
                self.assertFalse((output / "request_002.json").exists())

    def test_timeout_is_unknown_cost_and_never_retried(self):
        def timeout(_):
            raise httpx.ReadTimeout("PRIVATE_TIMEOUT_SENTINEL")
        summary = self.execute(timeout)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(summary["missingCostCount"], 1)
        record = json.loads((self.base / "output" / "response_001.json").read_bytes())
        self.assertEqual(record["errorCode"], "timeout")
        self.assertNotIn("PRIVATE_TIMEOUT_SENTINEL", json.dumps(record))

    def test_actual_cost_limits_stop_next_call_or_mark_last_overrun(self):
        summary = self.execute(lambda _: httpx.Response(200, json=response(cost=0.499)), output=self.base / "budget")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(summary["stopReason"], "budget_limit")
        self.calls = []
        plan = module.build_plan(self.cases[:1], "Persona", "Rules", 0.50)
        costs = iter([0.001, 0.51])
        summary = self.execute(lambda _: httpx.Response(200, json=response(cost=next(costs))),
                               plan=plan, output=self.base / "last_overrun")
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(summary["complete"])
        self.assertEqual(summary["stopReason"], "reported_budget_exceeded")
        self.assertEqual(summary["reportedCostUsd"], 0.511)

    def test_dispatch_checkpoint_precedes_calls_and_files_are_private(self):
        output = self.base / "new-parent" / "output"
        def handler(request):
            index = len(self.calls)
            marker = json.loads((output / f"request_{index:03d}.json").read_bytes())
            self.assertEqual(marker["status"], "dispatching")
            self.assertEqual(request.headers["X-OpenRouter-Cache"], "false")
            self.assertTrue((output / "plan.json").exists())
            return httpx.Response(200, json=response())
        summary = self.execute(handler, output=output)
        self.assertTrue(summary["complete"])
        self.assertEqual(len(self.calls), 4)
        self.assertEqual(summary["scope"], "isolated_persona_prompt_layer")
        self.assertIn("poller", summary["limitations"][0])
        plan_file = json.loads((output / "plan.json").read_bytes())
        self.assertEqual(plan_file["scope"], summary["scope"])
        for path in [output.parent, output]:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        for path in output.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_failed_dispatch_checkpoint_prevents_paid_call(self):
        original = module.write_private_json
        def fail_marker(path, value):
            if path.name.startswith("request_"):
                raise module.AnalysisError("synthetic_write_failure", "Synthetic error")
            return original(path, value)
        with patch.object(module, "write_private_json", side_effect=fail_marker):
            with self.assertRaises(module.AnalysisError):
                self.execute()
        self.assertEqual(len(self.calls), 0)

    def test_failed_response_checkpoint_leaves_intent_and_never_resends(self):
        original = module.write_private_json
        def fail_response(path, value):
            if path.name.startswith("response_"):
                raise module.AnalysisError("synthetic_write_failure", "Synthetic error")
            return original(path, value)
        with patch.object(module, "write_private_json", side_effect=fail_response):
            with self.assertRaises(module.AnalysisError):
                self.execute()
        self.assertEqual(len(self.calls), 1)
        self.assertTrue((self.base / "output" / "request_001.json").exists())
        self.assertFalse((self.base / "output" / "summary.json").exists())
        with self.assertRaisesRegex(module.EvaluationError, "output_exists"):
            self.execute()
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
