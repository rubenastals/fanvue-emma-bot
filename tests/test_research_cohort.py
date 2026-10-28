"""Cohort invariants using only fictional accounts and synthetic local evidence."""
import copy
import hashlib
import json
import stat

import pytest

from lab import research_cohort as module


def evidence(tmp_path, name, payload):
    raw = json.dumps(payload).encode()
    (tmp_path / name).write_bytes(raw)
    return {"file": name, "sha256": hashlib.sha256(raw).hexdigest()}


def manifest(tmp_path):
    revenue_file = evidence(tmp_path, "revenue.json", {"fictional": True, "amountMinor": 1200})
    chat_file = evidence(tmp_path, "chat.json", {"fictional": True, "messages": []})
    return {
        "schemaVersion": module.INPUT_SCHEMA,
        "purpose": "offline_conversation_research",
        "authorizations": {"analysis": "authorized", "evaluation": "authorized", "training": "not_recorded",
                           "basis": "Synthetic fixture; no customer permissions asserted."},
        "exclusions": [], "split": {"unit": "account", "seed": "fixed-synthetic-seed", "holdoutPercent": 20},
        "accounts": [{
            "accountKey": "fictional_account_a", "identity": {"accountId": "fictional-id-a", "connectionId": "fictional-connection-a", "handle": "sample.creator"},
            "classification": "real_verified", "classificationBasis": "Fictional verified-customer fixture.",
            "active": True, "observedAt": "2026-10-28T10:00:00Z",
            "revenueEvidence": [{**revenue_file, "source": "fanvue_api", "verifiedAt": "2026-10-28T10:00:00Z",
                                 "recordLocator": "fictional-row-1", "accountId": "fictional-id-a", "metric": "gross_earnings",
                                 "amountMinor": 1200, "currency": "USD", "periodStart": "2026-10-01T00:00:00Z", "periodEnd": "2026-10-28T09:59:00Z"}],
            "conversations": [{**chat_file, "conversationKey": "fictional_chat_a", "firstMessageId": "message_001", "lastMessageId": "message_020",
                               "messageCount": 20, "rangeStart": "2026-10-27T12:00:00Z", "rangeEnd": "2026-10-27T12:30:00Z", "truncated": True}],
        }],
    }


def compile_value(value, tmp_path):
    return module.compile_cohort(value, evidence_directory=tmp_path)


def add_purchase(value, tmp_path):
    proof = evidence(tmp_path, "purchase.json", {"fictional": True, "eventId": "fictional-event-1"})
    event = {**proof, "source": "fanvue_api", "verifiedAt": "2026-10-28T10:00:00Z", "recordLocator": "fictional-event-1",
             "accountId": "fictional-id-a", "conversationKey": "fictional_chat_a", "eventId": "fictional-event-1",
             "kind": "purchase", "amountMinor": 400, "currency": "USD", "occurredAt": "2026-10-27T12:20:00Z"}
    value["accounts"][0]["conversations"][0]["purchaseEvidence"] = [event]


def test_positive_revenue_selects_account_without_inventing_purchase_or_training(tmp_path):
    result = compile_value(manifest(tmp_path), tmp_path)
    account = result["accounts"][0]
    conversation = account["conversations"][0]
    assert account["eligibility"] == "eligible"
    assert conversation["commercialOutcome"] == "unknown"
    assert conversation["analysisReadiness"] == "ready_for_review"
    assert conversation["evaluationReadiness"] == "blocked"
    assert conversation["trainingReadiness"] == "unsupported"
    assert not result["trainingExportAllowed"]
    assert not conversation["purchaseCausalityEstablished"]
    assert conversation["firstMessageId"] == "message_001"
    assert conversation["rangeEnd"] == "2026-10-27T12:30:00Z"


@pytest.mark.parametrize("selector", [
    {"accountId": " FICTIONAL-ID-A "},
    {"connectionId": "FICTIONAL-CONNECTION-A"},
    {"handle": " @ＳＡＭＰＬＥ.CREATOR "},
])
def test_explicit_exclusion_overrides_verified_revenue_and_blocks_other_connections(tmp_path, monkeypatch, selector):
    value = manifest(tmp_path)
    other = copy.deepcopy(value["accounts"][0])
    other["accountKey"] = "second_connection"
    other["identity"]["connectionId"] = "different_connection"
    other["identity"]["handle"] = "different.handle"
    value["accounts"].append(other)
    value["exclusions"] = [{**selector, "reason": "owner_declared_test"}]
    monkeypatch.setattr(module, "_hash_evidence", lambda *_: pytest.fail("Excluded evidence must not be opened"))
    result = compile_value(value, tmp_path)
    assert result["summary"]["excluded"] == 2
    assert all(a["conversations"][0]["partition"] is None for a in result["accounts"])
    assert all(a["conversations"][0]["analysisReadiness"] == "blocked" for a in result["accounts"])


@pytest.mark.parametrize("classification,status", [("test", "excluded"), ("unknown", "pending_evidence")])
def test_classification_cannot_be_overridden_by_positive_revenue(tmp_path, classification, status):
    value = manifest(tmp_path)
    value["accounts"][0]["classification"] = classification
    assert compile_value(value, tmp_path)["accounts"][0]["eligibility"] == status


@pytest.mark.parametrize("amount", [0, -20])
def test_verified_nonpositive_revenue_is_distinct_from_missing_evidence(tmp_path, amount):
    value = manifest(tmp_path)
    value["accounts"][0]["revenueEvidence"][0]["amountMinor"] = amount
    account = compile_value(value, tmp_path)["accounts"][0]
    assert account["eligibility"] == "pending_evidence"
    assert account["revenueKnown"] is True
    assert "no_positive_revenue_in_verified_period" in account["eligibilityReasons"]
    value["accounts"][0]["revenueEvidence"] = []
    account = compile_value(value, tmp_path)["accounts"][0]
    assert account["revenueKnown"] is False
    assert account["revenueEvidence"] == []
    assert account["eligibilityReasons"] == ["revenue_evidence_missing"]


def test_permissions_and_non_explicit_review_are_separate_from_eligibility(tmp_path):
    value = manifest(tmp_path)
    value["authorizations"].update(analysis="denied", evaluation="not_recorded", training="authorized")
    value["accounts"][0]["conversations"][0]["review"] = "approved_non_explicit"
    result = compile_value(value, tmp_path)
    conversation = result["accounts"][0]["conversations"][0]
    assert result["accounts"][0]["eligibility"] == "eligible"
    assert conversation["analysisReadiness"] == conversation["evaluationReadiness"] == "blocked"
    assert conversation["trainingReadiness"] == "unsupported"
    value["authorizations"]["evaluation"] = "authorized"
    assert compile_value(value, tmp_path)["accounts"][0]["conversations"][0]["evaluationReadiness"] == "ready_for_review"


def test_verified_event_must_belong_to_same_account_and_conversation(tmp_path):
    value = manifest(tmp_path)
    add_purchase(value, tmp_path)
    conversation = compile_value(value, tmp_path)["accounts"][0]["conversations"][0]
    assert conversation["commercialOutcome"] == "verified_events_recorded"
    assert not conversation["purchaseCausalityEstablished"]
    value["accounts"][0]["conversations"][0]["purchaseEvidence"][0]["conversationKey"] = "other_chat"
    with pytest.raises(module.CohortError, match="purchase_attribution_mismatch"):
        compile_value(value, tmp_path)


def test_duplicate_payment_is_not_counted_twice(tmp_path):
    value = manifest(tmp_path)
    add_purchase(value, tmp_path)
    events = value["accounts"][0]["conversations"][0]["purchaseEvidence"]
    events.append(copy.deepcopy(events[0]))
    with pytest.raises(module.CohortError, match="duplicate_purchase_event"):
        compile_value(value, tmp_path)


def test_evidence_hash_is_checked_before_account_is_admitted(tmp_path):
    value = manifest(tmp_path)
    (tmp_path / "revenue.json").write_text('{"changed":true}')
    with pytest.raises(module.CohortError, match="evidence_hash_mismatch"):
        compile_value(value, tmp_path)


def test_revenue_from_another_account_cannot_select_this_account(tmp_path):
    value = manifest(tmp_path)
    value["accounts"][0]["revenueEvidence"][0]["accountId"] = "another-fictional-account"
    with pytest.raises(module.CohortError, match="revenue_account_mismatch"):
        compile_value(value, tmp_path)


def test_split_keeps_all_account_conversations_together_and_is_order_independent(tmp_path):
    value = manifest(tmp_path)
    for i in range(1, 12):
        chat = copy.deepcopy(value["accounts"][0]["conversations"][0])
        chat["conversationKey"] = f"fictional_chat_{i}"
        value["accounts"][0]["conversations"].append(chat)
    result = compile_value(value, tmp_path)
    initial = {c["conversationKey"]: c["partition"] for c in result["accounts"][0]["conversations"]}
    assert len(set(initial.values())) == 1
    value["accounts"][0]["conversations"].reverse()
    replay = compile_value(value, tmp_path)
    assert {c["conversationKey"]: c["partition"] for c in replay["accounts"][0]["conversations"]} == initial


def test_conversation_split_stays_stable_but_discloses_account_leakage_risk(tmp_path):
    value = manifest(tmp_path)
    value["split"]["unit"] = "conversation"
    result = compile_value(value, tmp_path)
    assert any("Conversation split" in x for x in result["limitations"])
    assert result["split"]["unit"] == "conversation"


def test_identical_source_conversation_cannot_cross_partitions(tmp_path):
    value = manifest(tmp_path)
    other = copy.deepcopy(value["accounts"][0])
    other["accountKey"] = "fictional_account_e"
    other["identity"]["accountId"] = "fictional-id-e"
    other["identity"]["connectionId"] = "fictional-connection-e"
    other["revenueEvidence"][0]["accountId"] = "fictional-id-e"
    value["accounts"].append(other)
    with pytest.raises(module.CohortError, match="source_reused_across_partitions"):
        compile_value(value, tmp_path)


@pytest.mark.parametrize("mutation", [
    lambda v: v["accounts"][0].update(text="must not accept chat content"),
    lambda v: v["accounts"][0]["revenueEvidence"][0].update(amountMinor=True),
    lambda v: v["accounts"][0]["revenueEvidence"][0].update(periodEnd="2026-09-01T00:00:00Z"),
    lambda v: v["accounts"][0].update(observedAt="2026-10-28T10:00:00"),
    lambda v: v.update(exclusions=[{"reason": "owner_declared_test"}]),
])
def test_invalid_or_extra_metadata_is_rejected_without_echoing_it(tmp_path, mutation):
    value = manifest(tmp_path)
    mutation(value)
    with pytest.raises(module.CohortError, match="invalid_manifest") as exc:
        compile_value(value, tmp_path)
    assert "must not accept" not in str(exc.value)


@pytest.mark.parametrize("name", ["../outside.json", "/tmp/outside.json"])
def test_evidence_cannot_escape_manifest_directory(tmp_path, name):
    value = manifest(tmp_path)
    value["accounts"][0]["revenueEvidence"][0]["file"] = name
    with pytest.raises(module.CohortError, match="evidence_path_outside_manifest"):
        compile_value(value, tmp_path)


def test_symlink_evidence_is_rejected(tmp_path):
    value = manifest(tmp_path)
    (tmp_path / "alias.json").symlink_to(tmp_path / "revenue.json")
    value["accounts"][0]["revenueEvidence"][0]["file"] = "alias.json"
    with pytest.raises(module.CohortError, match="unsafe_evidence_path"):
        compile_value(value, tmp_path)


def test_cli_saves_private_manifest_without_printing_identity(tmp_path, capsys):
    value = manifest(tmp_path)
    source = tmp_path / "manifest.json"
    source.write_text(json.dumps(value))
    output = tmp_path / "new" / "cohort.json"
    assert module.main(["--input", str(source), "--output", str(output)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"status": "saved", "accounts": 1, "eligible": 1, "pending_evidence": 0, "excluded": 0, "trainingExportAllowed": False}
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
    assert module.main(["--input", str(source), "--output", str(output)]) == 2
    assert json.loads(capsys.readouterr().out)["errorCode"] == "output_exists"
    with pytest.raises(module.CohortError, match="private_path_required"):
        module.write_private(module.ROOT / "docs" / "not-private.json", {})
