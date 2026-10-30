"""Offline dataset invariants with synthetic data; no customer files or providers."""
import contextlib
import copy
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lab import chat_dataset as module
from lab.real_chat_analysis import prepare_sample


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.raw_path = self.base / "raw.json"
        self.prepared_path = self.base / "prepared.json"
        self.review_path = self.base / "review.json"
        self.raw = {
            "schemaVersion": "fanvue.chat-export.v1", "truncated": False,
            "conversations": [
                {"id": f"source-local-{i}", "truncated": False, "messages": [
                    {"role": role, "text": text, "sentAt": f"2026-10-30T10:0{j}:00Z", "hasMedia": False}
                    for j, (role, text) in enumerate([
                        ("fan", f"Case {i}: how was your day?"),
                        ("creator", f"Case {i}: I spent a quiet afternoon reading."),
                        ("fan", f"Case {i}: please change the topic."),
                        ("creator", f"Case {i}: of course, we can talk about something else."),
                        ("creator", f"Case {i}: no problem at all."),
                    ])
                ]} for i in range(2)
            ],
        }
        self.review = {
            "schemaVersion": module.SCHEMA, "purpose": "non_explicit_response_training",
            "source": {"accountId": "synthetic-account-a", "connectionId": "synthetic-connection-a",
                       "handle": "synthetic.customer", "classification": "real_customer",
                       "classificationBasis": "Synthetic test fixture, never a customer.",
                       "rawFile": "raw.json", "rawBytesSha256": "0" * 64,
                       "rawCanonicalSha256": "0" * 64, "preparedBytesSha256": "0" * 64},
            "authorizationBasis": "Synthetic fixture only.", "reviewer": "synthetic-reviewer",
            "reviewedAt": "2026-10-30T12:00:00Z",
            "approvalScope": "entire_example_privacy_and_non_explicit",
            "split": {"seed": "fixed-synthetic-seed", "holdoutPercent": 20},
            "conversations": [
                {"id": f"chat_{i + 1:03d}", "stableKey": self.partition_key(i == 1),
                 "sourceConversationIndex": i, "sourceMessageStart": 0} for i in range(2)
            ],
            "examples": [
                {"id": f"example_{i}", "conversationId": f"chat_{i + 1:03d}",
                 "contextMessageIds": ["message_001"], "targetMessageIds": ["message_002"],
                 "status": "approved_non_explicit", "textOnlySufficient": True} for i in range(2)
            ],
        }
        self.prepare()

    @staticmethod
    def partition_key(evaluation):
        # Deliberately construct synthetic fixtures in each bucket; never used on real data.
        for i in range(1000):
            key = f"synthetic-stable-conversation-{i}"
            bucket = int(module.sha(module.canonical(["fixed-synthetic-seed", "synthetic-account-a", key])), 16) % 100
            if (bucket < 20) == evaluation:
                return key
        raise AssertionError("Could not construct fixture")

    def save_review(self):
        self.review_path.write_bytes(module.canonical(self.review))

    def prepare(self, messages_per_chat=100):
        self.raw_path.write_text(json.dumps(self.raw, indent=2), encoding="utf-8")
        self.prepared = prepare_sample(self.raw, max_chats=5, messages_per_chat=messages_per_chat)
        self.prepared_path.write_bytes(module.canonical(self.prepared))
        self.review["source"].update(
            rawBytesSha256=module.sha(self.raw_path.read_bytes()),
            rawCanonicalSha256=module.sha(module.canonical(self.raw)),
            preparedBytesSha256=module.sha(self.prepared_path.read_bytes()),
        )
        self.save_review()

    def save_prepared(self, update_review=True):
        self.prepared_path.write_bytes(module.canonical(self.prepared))
        if update_review:
            self.review["source"]["preparedBytesSha256"] = module.sha(self.prepared_path.read_bytes())
        self.save_review()

    def build(self):
        return module.build_dataset(self.prepared_path, self.review_path)

    def assert_code(self, code):
        with self.assertRaises(module.DatasetError) as caught:
            self.build()
        self.assertEqual(caught.exception.code, code)

    def test_valid_output_reserves_reference_and_is_a_pilot(self):
        result = self.build()
        self.assertEqual(len(result["train"]), 1)
        self.assertEqual(len(result["evaluation"]), 1)
        self.assertEqual([m["role"] for m in result["train"][0]["messages"]], ["user", "assistant"])
        case = result["evaluation"][0]
        self.assertEqual([m["role"] for m in case["inputMessages"]], ["user"])
        self.assertEqual(case["referenceResponse"]["role"], "assistant")
        self.assertEqual(result["manifest"]["readiness"], "pilot")
        self.assertFalse(result["manifest"]["readyForTraining"])
        self.assertFalse(result["manifest"]["trainingJobStarted"])

    def test_owner_test_each_identifier_is_blocked_before_content_reads(self):
        original = copy.deepcopy(self.review)
        variants = [("accountId", "  EXCLUDED-SYNTHETIC-ACCOUNT  ", "EXCLUDED_ACCOUNT_SHA256", "excluded-synthetic-account"),
                    ("connectionId", "EXCLUDED-SYNTHETIC-CONNECTION", "EXCLUDED_CONNECTION_SHA256", "excluded-synthetic-connection"),
                    ("handle", "  @ＳＹＮＴＨＥＴＩＣ.ＴＥＳＴ  ", "EXCLUDED_HANDLE_SHA256", "synthetic.test")]
        for field, value, fingerprint_name, normalized_fixture in variants:
            with self.subTest(field=field):
                self.review = copy.deepcopy(original)
                self.review["source"][field] = value
                self.save_review()
                with patch.object(module, fingerprint_name, module.sha(normalized_fixture.encode())), \
                        patch.object(module, "load_json", wraps=module.load_json) as reader:
                    self.assert_code("excluded_owner_test_source")
                self.assertEqual(reader.call_count, 1)
                self.assertEqual(reader.call_args.args[0], self.review_path)

    def test_no_approval_reads_only_review_and_writes_nothing(self):
        self.review["examples"][0]["status"] = "pending"
        self.review["examples"][1]["status"] = "rejected"
        self.save_review()
        output = self.base / "never-created"
        with patch.object(module, "load_json", wraps=module.load_json) as reader:
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                code = module.main(["--prepared", str(self.prepared_path), "--review", str(self.review_path),
                                    "--output-dir", str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(reader.call_count, 1)
        self.assertFalse(output.exists())
        self.assertEqual(json.loads(capture.getvalue())["code"], "no_approved_examples")

    def test_pending_and_rejected_examples_never_enter_exports(self):
        self.review["examples"][1]["status"] = "rejected"
        pending = copy.deepcopy(self.review["examples"][0])
        pending.update(id="later_pending", contextMessageIds=["message_003"],
                       targetMessageIds=["message_004", "message_005"], status="pending")
        self.review["examples"].append(pending)
        self.save_review()
        result = self.build()
        self.assertEqual(result["manifest"]["counts"]["trainExamples"], 1)
        self.assertEqual(result["manifest"]["counts"]["evaluationExamples"], 0)
        self.assertEqual(result["manifest"]["readiness"], "insufficient")
        self.assertNotIn("Case 1:", json.dumps(result))
        self.assertNotIn("no problem", json.dumps(result))

    def test_raw_byte_and_canonical_hashes_are_distinct_and_both_checked(self):
        source = self.review["source"]
        self.assertNotEqual(source["rawBytesSha256"], source["rawCanonicalSha256"])
        self.raw_path.write_bytes(self.raw_path.read_bytes() + b"\n")
        self.assert_code("raw_bytes_hash_mismatch")
        source["rawBytesSha256"] = module.sha(self.raw_path.read_bytes())
        self.save_review()
        self.build()  # Whitespace changed bytes but not the canonical source.
        source["rawCanonicalSha256"] = "1" * 64
        self.save_review()
        self.assert_code("raw_canonical_hash_mismatch")

    def test_edit_after_review_is_rejected(self):
        self.prepared["conversations"][0]["messages"][1]["text"] = "Edited after approval"
        self.save_prepared(update_review=False)
        self.assert_code("prepared_review_hash_mismatch")

    def test_prepared_must_name_the_actual_canonical_source(self):
        self.prepared["sourceSha256"] = "2" * 64
        self.save_prepared()
        self.assert_code("prepared_source_hash_mismatch")

    def test_reapproval_cannot_change_roles_times_or_media_facts(self):
        original = copy.deepcopy(self.prepared)
        for field, value in [("role", "fan"), ("minutesFromStart", 12), ("hasMedia", True)]:
            with self.subTest(field=field):
                self.prepared = copy.deepcopy(original)
                self.prepared["conversations"][0]["messages"][1][field] = value
                self.save_prepared()
                self.assert_code("source_facts_changed")

    def test_reviewed_text_can_be_further_minimized(self):
        self.prepared["conversations"][0]["messages"][1]["text"] = "A quiet afternoon with [NAME_1]."
        self.save_prepared()
        self.assertIn("[NAME_1]", json.dumps(self.build()))

    def test_approval_covers_text_only_context_and_target(self):
        self.review["examples"][0]["textOnlySufficient"] = False
        self.save_review()
        self.assert_code("text_only_review_required")

    def test_window_can_start_later_and_groups_complete_creator_turn(self):
        self.review["examples"][0].update(contextMessageIds=["message_003"],
                                          targetMessageIds=["message_004", "message_005"])
        self.save_review()
        messages = self.build()["train"][0]["messages"]
        self.assertEqual(len(messages), 2)
        self.assertIn("\n\n", messages[-1]["content"])
        self.assertNotIn("afternoon", json.dumps(messages))

    def test_only_last_assistant_turn_is_the_declared_training_target(self):
        self.review["examples"][0].update(contextMessageIds=["message_001", "message_002", "message_003"],
                                          targetMessageIds=["message_004", "message_005"])
        self.save_review()
        example = self.build()["train"][0]
        self.assertEqual([m["role"] for m in example["messages"]], ["user", "assistant", "user", "assistant"])
        self.assertEqual(example["targetMessageIndex"], 3)

    def test_binding_a_prepared_tail_requires_the_correct_source_start(self):
        self.prepare(messages_per_chat=3)
        for example in self.review["examples"]:
            example["targetMessageIds"] = ["message_002", "message_003"]
        self.save_review()
        self.assert_code("source_facts_changed")
        for binding in self.review["conversations"]:
            binding["sourceMessageStart"] = 2
        self.save_review()
        self.build()

    def test_future_reordered_duplicate_or_missing_ids_are_rejected(self):
        original = copy.deepcopy(self.review["examples"][0])
        variants = [(["message_003"], ["message_002"], "noncontiguous_or_future_context"),
                    (["message_001", "message_003"], ["message_004", "message_005"], "noncontiguous_or_future_context"),
                    (["message_001", "message_001"], ["message_002"], "invalid_example_messages"),
                    (["message_099"], ["message_002"], "invalid_example_messages")]
        for context, target, code in variants:
            with self.subTest(code=code, context=context):
                self.review["examples"][0] = copy.deepcopy(original)
                self.review["examples"][0].update(contextMessageIds=context, targetMessageIds=target)
                self.save_review()
                self.assert_code(code)

    def test_incomplete_creator_turn_and_wrong_role_boundaries_are_rejected(self):
        self.review["examples"][0].update(contextMessageIds=["message_003"], targetMessageIds=["message_004"])
        self.save_review()
        self.assert_code("incomplete_creator_turn")
        self.review["examples"][0].update(contextMessageIds=["message_002"], targetMessageIds=["message_003"])
        self.save_review()
        self.assert_code("invalid_role_boundary")

    def test_prepared_boundary_cannot_hide_a_known_creator_continuation(self):
        self.prepared["conversations"][0]["messages"] = self.prepared["conversations"][0]["messages"][:4]
        self.prepared["conversations"][0]["truncated"] = True
        self.review["examples"][0].update(contextMessageIds=["message_003"], targetMessageIds=["message_004"])
        self.save_prepared()
        self.assert_code("incomplete_creator_turn")

    def test_unknown_or_empty_messages_are_not_training_targets(self):
        for field, value, code in [("role", "unknown", "invalid_role_boundary"),
                                   ("text", None, "unusable_message"), ("text", "  ", "unusable_message")]:
            with self.subTest(field=field, value=value):
                self.raw["conversations"][0]["messages"][1].update(role="creator", text="Valid text")
                self.raw["conversations"][0]["messages"][1][field] = value
                self.prepare()
                self.assert_code(code)

    def test_media_with_text_requires_attested_independence_and_is_not_exported(self):
        self.raw["conversations"][0]["messages"][1]["hasMedia"] = True
        self.raw["conversations"][0]["messages"][1]["mediaUrl"] = "https://synthetic.invalid/private"
        self.prepare()
        result = self.build()
        self.assertNotIn("mediaUrl", json.dumps(result))
        self.assertNotIn("https://", json.dumps(result))

    def test_review_cannot_turn_media_only_into_a_text_target(self):
        for original in (None, "", "  "):
            with self.subTest(original=original):
                self.raw["conversations"][0]["messages"][1].update(text=original, hasMedia=True)
                self.prepare()
                self.prepared["conversations"][0]["messages"][1]["text"] = "[MEDIA OMITTED]"
                self.save_prepared()
                self.assert_code("source_text_presence_changed")

    def test_multiple_windows_of_one_conversation_share_partition(self):
        later = copy.deepcopy(self.review["examples"][0])
        later.update(id="later", contextMessageIds=["message_003"], targetMessageIds=["message_004", "message_005"])
        self.review["examples"].append(later)
        self.save_review()
        allocations = self.build()["manifest"]["allocations"]
        train_groups = {a["conversationGroup"] for a in allocations if a["partition"] == "train"}
        evaluation_groups = {a["conversationGroup"] for a in allocations if a["partition"] == "evaluation"}
        self.assertTrue(train_groups.isdisjoint(evaluation_groups))
        self.assertEqual(sum(a["partition"] == "train" for a in allocations), 2)

    def test_duplicate_history_under_different_keys_is_grouped_and_deduplicated(self):
        self.raw["conversations"][1] = copy.deepcopy(self.raw["conversations"][0])
        self.prepare()
        result = self.build()
        self.assertEqual(result["manifest"]["counts"]["duplicatesRemoved"], 1)
        self.assertEqual(result["manifest"]["counts"]["conversationGroups"], 1)
        self.assertEqual(len(result["train"]) + len(result["evaluation"]), 1)

    def test_identical_context_with_different_targets_never_crosses_split(self):
        self.raw["conversations"][1]["messages"][0]["text"] = self.raw["conversations"][0]["messages"][0]["text"]
        self.prepare()
        allocations = self.build()["manifest"]["allocations"]
        self.assertEqual(len({a["partition"] for a in allocations}), 1)
        self.assertEqual(len({a["conversationGroup"] for a in allocations}), 1)

    def test_same_stable_key_groups_multiple_local_ids(self):
        self.review["conversations"][1]["stableKey"] = self.review["conversations"][0]["stableKey"]
        self.save_review()
        self.assertEqual(self.build()["manifest"]["counts"]["conversationGroups"], 1)

    def test_two_windows_of_same_raw_conversation_never_cross_split(self):
        windows = []
        for start, end in ((0, 2), (2, 5)):
            partial_raw = {"schemaVersion": "fanvue.chat-export.v1", "truncated": True,
                           "conversations": [{"truncated": True,
                                              "messages": self.raw["conversations"][0]["messages"][start:end]}]}
            windows.append(prepare_sample(partial_raw)["conversations"][0])
        windows[1]["id"] = "chat_002"
        self.prepared["conversations"] = windows
        self.review["conversations"][1].update(sourceConversationIndex=0, sourceMessageStart=2)
        self.review["examples"][1]["targetMessageIds"] = ["message_002", "message_003"]
        self.save_prepared()
        allocations = self.build()["manifest"]["allocations"]
        self.assertEqual(len(allocations), 2)
        self.assertEqual(len({a["conversationGroup"] for a in allocations}), 1)
        self.assertEqual(len({a["partition"] for a in allocations}), 1)

    def test_reordering_review_entries_does_not_change_split_or_outputs(self):
        before = self.build()
        self.review["examples"].reverse()
        self.review["conversations"].reverse()
        self.save_review()
        after = self.build()
        for key in ("train", "evaluation"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(before["manifest"]["allocations"], after["manifest"]["allocations"])

    def test_local_chat_id_is_not_accepted_as_stable_key(self):
        for value in ("chat_001", " chat_001 ", "ｃｈａｔ＿００１", "CHAT_001"):
            with self.subTest(value=value):
                self.review["conversations"][0]["stableKey"] = value
                self.save_review()
                self.assert_code("unstable_conversation_key")

    def test_paths_cannot_escape_or_follow_symlinks(self):
        for path in ("../raw.json", str(self.raw_path), ".hidden.json"):
            with self.subTest(path=path):
                self.review["source"]["rawFile"] = path
                self.save_review()
                self.assert_code("invalid_source_path")
        (self.base / "linked.json").symlink_to(self.raw_path)
        self.review["source"]["rawFile"] = "linked.json"
        self.save_review()
        self.assert_code("symlink_not_allowed")

    def test_manifest_has_no_account_identity_reviewer_or_text(self):
        manifest = json.dumps(self.build()["manifest"])
        for private in ("synthetic-account-a", "synthetic-connection-a", "synthetic.customer",
                        "synthetic-reviewer", "how was your day", "synthetic-stable-conversation-"):
            self.assertNotIn(private, manifest)

    def test_offline_build_does_not_access_network_or_configuration(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), \
                patch("lab.real_chat_analysis.load_dotenv", side_effect=AssertionError("secrets forbidden")):
            self.build()

    def test_private_files_hashes_permissions_and_no_overwrite(self):
        output = module.write_dataset(self.base / "new" / "dataset", self.build())
        self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
        manifest = json.loads((output / "manifest.json").read_bytes())
        for path in output.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            if path.name != "manifest.json":
                self.assertEqual(manifest["files"][path.name]["sha256"], module.sha(path.read_bytes()))
        with self.assertRaises(module.DatasetError) as caught:
            module.write_dataset(output, self.build())
        self.assertEqual(caught.exception.code, "output_exists")

    def test_write_failure_removes_new_partial_bundle(self):
        output = self.base / "partial"
        original_open = os.open
        calls = 0

        def broken_open(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("synthetic disk failure")
            return original_open(*args, **kwargs)

        with patch.object(module.os, "open", side_effect=broken_open):
            with self.assertRaises(module.DatasetError) as caught:
                module.write_dataset(output, self.build())
        self.assertEqual(caught.exception.code, "output_failed")
        self.assertFalse(output.exists())

    def test_source_directory_output_is_rejected(self):
        with self.assertRaises(module.DatasetError) as caught:
            module.write_dataset(module.ROOT / "docs" / "never-dataset", self.build())
        self.assertEqual(caught.exception.code, "unsafe_output_directory")

    def test_duplicate_json_keys_are_rejected(self):
        self.review_path.write_text('{"schemaVersion":"first","schemaVersion":"second"}')
        self.assert_code("duplicate_json_key")


if __name__ == "__main__":
    unittest.main()
