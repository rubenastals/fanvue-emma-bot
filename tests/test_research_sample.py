"""Synthetic research exports only; no credentials, live HTTP or customer text."""
import asyncio
import copy
import hashlib
import json
import stat

import httpx
import pytest

from lab import real_chat_analysis as analysis
from lab import research_cohort as cohort
from lab import research_sample as module


def source_export():
    event = {"id": "event_001", "occurredAt": "2026-09-03T12:00:00Z", "source": "message",
             "grossUsdCents": 1200, "netUsdCents": 1000, "totalUsdCents": 1200,
             "payoutStatus": "pendingBalance", "messageType": "SINGLE_RECIPIENT", "reversesEventId": None}
    return {
        "schemaVersion": module.SOURCE_SCHEMA,
        "purpose": "original_evidence_for_non_graphic_offline_analysis",
        "source": {"accountRef": "account_001", "provenance": "selected_authorized_connection",
                   "testAccountStatus": "requires_owner_review"},
        "earnings": {"schemaVersion": "fanvue.earnings-export.v1", "unit": "USD_cent", "complete": True,
                     "incompleteReason": None, "selectionEvidence": "positive_window_fan_net",
                     "verifiedWindowFanNetUsdCents": 5000, "verifiedWindowMessageNetUsdCents": 1000,
                     "window": {"startDate": "2026-09-01T00:00:00Z", "endDate": "2026-10-01T00:00:00Z", "endExclusive": True},
                     "limitations": ["ARBITRARY_EARNINGS_TEXT_MUST_NOT_REACH_MODEL"]},
        "selection": {"eligiblePurchaseCandidates": 4, "selectedDistinctFans": 1,
                      "positiveMessageRowsMissingJoinIds": 1, "reversedOrNonpositiveMessageRowsExcluded": 2,
                      "preference": "single_recipient_then_latest_purchase"},
        "conversations": [{"id": "chat_001", "participant": "fan_001", "events": [event],
            "messages": [
                {"id": "message_001", "sentAt": "2026-09-03T11:59:00Z", "role": "creator",
                 "text": "Puedes ver la oferta cuando quieras. contacto@example.test", "hasMedia": None,
                 "type": "SINGLE_RECIPIENT", "deliveryStatus": "SENT",
                 "attribution": {"appReferencePresent": False, "senderOperatorReferencePresent": False, "authoredByHuman": None}},
                {"id": "message_002", "sentAt": "2026-09-03T12:02:00Z", "role": "fan",
                 "text": "Gracias. Prefiero mensajes breves.", "hasMedia": None,
                 "type": "not_recognized", "deliveryStatus": "unknown",
                 "attribution": {"appReferencePresent": False, "senderOperatorReferencePresent": False, "authoredByHuman": None}},
                {"id": "message_003", "sentAt": None, "role": "unknown", "text": None, "hasMedia": True,
                 "type": "BROADCAST", "deliveryStatus": "UNSENT",
                 "attribution": {"appReferencePresent": True, "senderOperatorReferencePresent": True, "authoredByHuman": None}},
            ],
            "context": {"selection": "most_recent_messages", "messagesLimit": 50, "truncated": True,
                        "containsPostPurchaseMessages": True, "historicalTextAtPurchaseVerified": False},
            "purchase": {"eventId": "event_001", "adjustedNetUsdCents": 1000, "joinStatus": "linked",
                         "messageId": "message_001", "creatorAndFanMatch": True,
                         "messagePrecedesPurchase": True, "causalEffectVerified": False}}],
        "limitations": ["ARBITRARY_SOURCE_TEXT_MUST_NOT_REACH_MODEL"],
        "ignoredPrivateMetadata": "DO_NOT_TRANSMIT_THIS_METADATA",
    }


def write(path, value):
    path.write_bytes(analysis._json_bytes(value) + b"\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def files(tmp_path, *, partition="development", source=None):
    split = cohort.Split(unit="account", seed="synthetic-stable-seed", holdoutPercent=20)
    account_id = next(f"fictional-account-{i}" for i in range(100)
                      if cohort._partition(split, f"fictional-account-{i}", "") == partition)
    source = source if source is not None else source_export()
    source_hash = write(tmp_path / "original.json", source)
    revenue_hash = write(tmp_path / "revenue.json", {"synthetic": True, "verifiedNet": 5000})
    manifest = {
        "schemaVersion": cohort.INPUT_SCHEMA, "purpose": "offline_conversation_research",
        "authorizations": {"analysis": "authorized", "evaluation": "authorized", "training": "authorized",
                           "basis": "Synthetic owner attestation for this test only."},
        "exclusions": [], "split": split.model_dump(),
        "accounts": [{"accountKey": "synthetic-client", "identity": {"accountId": account_id,
                        "connectionId": "synthetic-connection", "handle": "synthetic_handle"},
                      "classification": "real_verified", "classificationBasis": "Synthetic source for tests.",
                      "observedAt": "2026-10-02T00:00:00Z", "active": True,
                      "revenueEvidence": [{"source": "fanvue_verified_export", "file": "revenue.json",
                        "sha256": revenue_hash, "verifiedAt": "2026-10-02T00:00:00Z", "recordLocator": "verifiedNet",
                        "accountId": account_id, "metric": "net_earnings", "amountMinor": 5000, "currency": "USD",
                        "periodStart": "2026-09-01T00:00:00Z", "periodEnd": "2026-10-01T00:00:00Z"}],
                      "conversations": []}],
    }
    binding = {"schemaVersion": module.BINDING_SCHEMA, "sourceFile": "original.json", "sourceSha256": source_hash,
               "manifestFile": "manifest.json", "manifestSha256": write(tmp_path / "manifest.json", manifest),
               "accountKey": "synthetic-client",
               "analysisPurpose": "pattern_discovery" if partition == "development" else "heldout_evaluation"}
    path = tmp_path / "binding.json"
    write(path, binding)
    return path, manifest, binding


def update_manifest(binding_path, manifest, binding):
    binding["manifestSha256"] = write(binding_path.parent / "manifest.json", manifest)
    write(binding_path, binding)


def reviewed(path):
    return module.review_research(module.prepare_research(path), path)


def test_preserves_evidence_ids_signed_adjustments_chronology_and_privacy(tmp_path):
    source = source_export()
    chat = source["conversations"][0]
    for index, (kind, net) in enumerate((("refund", -100), ("chargeback", -50), ("earningsDeduction", -30),
                                         ("earningsDeduction", 20)), 2):
        chat["events"].append({**chat["events"][0], "id": f"event_{index:03d}", "source": kind,
                               "occurredAt": "2026-09-04T12:00:00Z", "grossUsdCents": 0,
                               "netUsdCents": net, "totalUsdCents": 0, "reversesEventId": "event_001"})
    chat["purchase"]["adjustedNetUsdCents"] = 840
    binding_path, manifest, _ = files(tmp_path, source=source)
    sample = reviewed(binding_path)
    request = analysis.make_request(sample, analysis.DEFAULT_MODEL, research_binding=binding_path)
    payload = json.loads(request["messages"][1]["content"])
    chat = payload["conversations"][0]
    assert [m["minutesFromPurchase"] for m in chat["messages"]] == [-1, 2, None]
    assert [e["netUsdCents"] for e in chat["events"]] == [1000, -100, -50, -30, 20]
    assert chat["events"][1]["minutesFromPurchase"] == 1440
    assert chat["purchase"]["adjustedNetUsdCents"] == 840
    assert chat["purchase"]["messageId"] == "message_001"
    assert chat["chronology"] == "unknown_times_present"
    assert chat["messages"][0]["hasMedia"] is None
    assert chat["messages"][0]["attribution"]["authoredByHuman"] is None
    assert chat["events"][0]["payoutStatus"] == "pendingBalance"
    assert "[EMAIL_1]" in chat["messages"][0]["text"]
    serialized = json.dumps(request)
    for removed in ("contacto@example.test", "ARBITRARY_", "DO_NOT_TRANSMIT", "2026-09", "synthetic-client",
                    manifest["accounts"][0]["identity"]["accountId"], sample["provenance"]["sourceBytesSha256"]):
        assert removed not in serialized
    assert "No hay datos de transacciones verificados" not in serialized
    assert request["provider"]["zdr"] is True and request["provider"]["allow_fallbacks"] is False


@pytest.mark.parametrize("case,expected", [
    ("deny_handle", "excluded_source"), ("test_other_connection", "excluded_source"),
    ("inactive", "inactive_source"), ("unknown", "pending_evidence"),
    ("no_income", "pending_evidence"), ("nonpositive", "pending_evidence"),
    ("wrong_account", "revenue_account_mismatch"), ("purpose", "partition_purpose_mismatch"),
    ("conversation_split", "account_split_required"), ("authorization", "action_not_authorized"),
    ("excluded_range", "excluded_conversation_source"),
])
def test_metadata_gates_precede_any_evidence_or_chat_open(tmp_path, monkeypatch, case, expected):
    path, manifest, binding = files(tmp_path)
    account = manifest["accounts"][0]
    if case == "deny_handle":
        manifest["exclusions"] = [{"handle": " @SYNTHETIC_HANDLE ", "reason": "owner_declared_test"}]
    elif case == "test_other_connection":
        other = copy.deepcopy(account)
        other.update(accountKey="synthetic-second", classification="test")
        other["identity"]["connectionId"] = "synthetic-second-connection"
        manifest["accounts"].append(other)
    elif case == "inactive":
        account["active"] = False
    elif case == "unknown":
        account["classification"] = "unknown"
    elif case == "no_income":
        account["revenueEvidence"] = []
    elif case == "nonpositive":
        account["revenueEvidence"][0]["amountMinor"] = 0
    elif case == "wrong_account":
        account["revenueEvidence"][0]["accountId"] = "unrelated-synthetic-account"
    elif case == "purpose":
        binding["analysisPurpose"] = "heldout_evaluation"
    elif case == "conversation_split":
        manifest["split"]["unit"] = "conversation"
    elif case == "authorization":
        manifest["authorizations"]["analysis"] = "denied"
    elif case == "excluded_range":
        account["conversations"] = [{"conversationKey": "chat_001", "file": "original.json",
            "sha256": binding["sourceSha256"], "firstMessageId": "message_001", "lastMessageId": "message_003",
            "messageCount": 3, "rangeStart": "2026-09-03T11:59:00Z", "rangeEnd": "2026-09-03T12:02:00Z",
            "truncated": True, "review": "excluded"}]
    update_manifest(path, manifest, binding)
    opened = []
    original = module.read_json
    def read_spy(file, **kwargs):
        opened.append(file.name)
        assert file.name in ("binding.json", "manifest.json")
        return original(file, **kwargs)
    monkeypatch.setattr(module, "read_json", read_spy)
    monkeypatch.setattr(cohort, "_hash_evidence", lambda *a: pytest.fail("evidence opened before gate"))
    with pytest.raises(analysis.AnalysisError) as exc:
        module.prepare_research(path)
    assert exc.value.code == expected
    assert opened == ["binding.json", "manifest.json"]


def test_unrelated_files_are_not_opened_and_manifest_source_hashes_are_checked(tmp_path):
    path, manifest, binding = files(tmp_path)
    unrelated = copy.deepcopy(manifest["accounts"][0])
    unrelated["accountKey"] = "another-synthetic-client"
    unrelated["identity"]["accountId"] = "another-synthetic-account"
    unrelated["revenueEvidence"][0]["file"] = "DOES_NOT_EXIST.json"
    manifest["accounts"].append(unrelated)
    update_manifest(path, manifest, binding)
    module.prepare_research(path)
    with (tmp_path / "original.json").open("ab") as file:
        file.write(b" ")
    with pytest.raises(analysis.AnalysisError) as exc:
        module.prepare_research(path)
    assert exc.value.code == "file_hash_mismatch"
    binding["sourceSha256"] = hashlib.sha256((tmp_path / "original.json").read_bytes()).hexdigest()
    write(path, binding)
    with (tmp_path / "manifest.json").open("ab") as file:
        file.write(b" ")
    with pytest.raises(analysis.AnalysisError) as exc:
        module.prepare_research(path)
    assert exc.value.code == "file_hash_mismatch"


def test_review_covers_exact_payload_and_immutable_source_facts(tmp_path):
    path, _, _ = files(tmp_path)
    sample = module.prepare_research(path)
    with pytest.raises(analysis.AnalysisError) as exc:
        analysis.make_request(sample, analysis.DEFAULT_MODEL, research_binding=path)
    assert exc.value.code == "non_explicit_review_required"
    # Operator can redact further during content review; structured evidence stays fixed.
    sample["payload"]["conversations"][0]["messages"][0]["text"] = "[DETAIL_REMOVED]"
    sample = module.review_research(sample, path)
    analysis.make_request(sample, analysis.DEFAULT_MODEL, research_binding=path)
    changed = copy.deepcopy(sample)
    changed["payload"]["conversations"][0]["messages"][0]["text"] = "An edit after review"
    with pytest.raises(analysis.AnalysisError) as exc:
        analysis.make_request(changed, analysis.DEFAULT_MODEL, research_binding=path)
    assert exc.value.code == "non_explicit_review_required"
    changed = copy.deepcopy(sample)
    changed["payload"]["conversations"][0]["events"][0]["netUsdCents"] += 1
    with pytest.raises(analysis.AnalysisError) as exc:
        module.review_research(changed, path)
    assert exc.value.code == "source_facts_changed"


def test_direct_python_api_blocks_before_client_and_cli_before_credentials(tmp_path, monkeypatch):
    path, _, _ = files(tmp_path)
    sample = module.prepare_research(path)
    monkeypatch.setattr(analysis.httpx, "AsyncClient", lambda **kw: pytest.fail("constructed client before gate"))
    for binding_path, code in ((None, "research_binding_required"), (path, "non_explicit_review_required")):
        with pytest.raises(analysis.AnalysisError) as exc:
            asyncio.run(analysis.analyze_sample(sample, [analysis.DEFAULT_MODEL], api_key="synthetic-key",
                                               research_binding=binding_path))
        assert exc.value.code == code
    write(tmp_path / "prepared.json", sample)
    monkeypatch.setattr(analysis, "load_dotenv", lambda *a, **kw: pytest.fail("loaded credentials before review"))
    assert module.main(["--analyze", "--binding", str(path), "--input", str(tmp_path / "prepared.json"),
                        "--output", str(tmp_path / "result.json")]) == 2
    assert not (tmp_path / "result.json").exists()


def test_holdout_cannot_be_repurposed_for_pattern_discovery(tmp_path):
    path, manifest, binding = files(tmp_path, partition="holdout")
    sample = reviewed(path)
    request = analysis.make_request(sample, analysis.DEFAULT_MODEL, research_binding=path)
    assert sample["payload"]["partition"] == "holdout"
    assert "no descubras patrones" in request["messages"][0]["content"]
    binding["analysisPurpose"] = "pattern_discovery"
    write(path, binding)
    with pytest.raises(analysis.AnalysisError) as exc:
        module.prepare_research(path)
    assert exc.value.code == "partition_purpose_mismatch"


def test_preserves_50_messages_and_explicit_chat_selection_without_renumbering(tmp_path):
    source = source_export()
    first = source["conversations"][0]
    first["messages"] = [{**first["messages"][1], "id": f"message_{i:03d}"} for i in range(1, 51)]
    first["purchase"].update(joinStatus="unlinked_message_not_in_context", messageId=None,
                             creatorAndFanMatch=None, messagePrecedesPurchase=None)
    second = copy.deepcopy(first)
    second.update(id="chat_002", participant="fan_002")
    source["conversations"].append(second)
    source["selection"]["selectedDistinctFans"] = 2
    path, _, _ = files(tmp_path, source=source)
    sample = module.prepare_research(path, conversation_ids=["chat_002"])
    chat = sample["payload"]["conversations"][0]
    assert chat["id"] == "chat_002" and len(chat["messages"]) == 50
    assert chat["messages"][-1]["id"] == "message_050"
    assert chat["purchase"]["messageId"] is None
    assert sample["payload"]["selection"]["selectedDistinctFans"] == 2


@pytest.mark.parametrize("change", ["net", "join", "sign", "authorship", "extra", "post_time",
    "literal_media", "literal_history", "literal_causality", "literal_complete", "literal_window_end",
    "long_window", "missing_message_precedes"])
def test_invalid_source_facts_rejected(tmp_path, change):
    source = source_export()
    chat = source["conversations"][0]
    if change == "net":
        chat["purchase"]["adjustedNetUsdCents"] += 1
    elif change == "join":
        chat["purchase"]["messageId"] = "message_002"
    elif change == "sign":
        chat["events"].append({**chat["events"][0], "id": "event_002", "source": "refund",
                               "reversesEventId": "event_001", "netUsdCents": 100})
        chat["purchase"]["adjustedNetUsdCents"] = 1100
    elif change == "authorship":
        chat["messages"][0]["attribution"]["authoredByHuman"] = True
    elif change == "extra":
        chat["messages"][0]["fanEmail"] = "never-send@example.test"
    elif change == "post_time":
        chat["context"]["containsPostPurchaseMessages"] = False
    elif change == "literal_media":
        chat["messages"][0]["hasMedia"] = 1
    elif change == "literal_history":
        chat["context"]["historicalTextAtPurchaseVerified"] = 0
    elif change == "literal_causality":
        chat["purchase"]["causalEffectVerified"] = 0.0
    elif change == "literal_complete":
        source["earnings"]["complete"] = 1.0
    elif change == "literal_window_end":
        source["earnings"]["window"]["endExclusive"] = 1
    elif change == "long_window":
        source["earnings"]["window"]["endDate"] = "2026-10-03T00:00:00Z"
    elif change == "missing_message_precedes":
        chat["purchase"].update(joinStatus="unlinked_message_not_in_context", messageId=None,
                                creatorAndFanMatch=None, messagePrecedesPurchase=True)
    path, _, _ = files(tmp_path, source=source)
    with pytest.raises(analysis.AnalysisError):
        module.prepare_research(path)


def test_model_event_references_are_scoped_to_chat_and_transport_stays_restricted(tmp_path):
    source = source_export()
    second = copy.deepcopy(source["conversations"][0])
    second.update(id="chat_002", participant="fan_002")
    second["events"].append({**second["events"][0], "id": "event_002", "source": "refund", "reversesEventId": "event_001",
                             "grossUsdCents": -100, "netUsdCents": -100, "totalUsdCents": -100})
    second["purchase"]["adjustedNetUsdCents"] = 900
    source["conversations"].append(second)
    source["selection"]["selectedDistinctFans"] = 2
    path, _, _ = files(tmp_path, source=source)
    sample = reviewed(path)
    document = {"kind": "analysis_only", "observations": [{"topic": "recorded_purchase",
                "finding": "Consta un evento positivo y un ajuste; no prueba causalidad.",
                "evidence": [{"conversationId": "chat_002", "messageIds": [], "eventIds": ["event_001", "event_002"]}]}],
                "limitations": ["Muestra seleccionada por compras positivas, sin denominador de conversión."]}
    analysis.validate_analysis(document, sample, research_binding=path)
    wrong = copy.deepcopy(document)
    wrong["observations"][0]["evidence"][0]["conversationId"] = "chat_001"
    with pytest.raises(analysis.AnalysisError) as exc:
        analysis.validate_analysis(wrong, sample, research_binding=path)
    assert exc.value.code == "invalid_evidence"
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == analysis.API_URL
        body = json.loads(request.content)
        assert body["provider"]["data_collection"] == "deny"
        assert request.headers["X-OpenRouter-Cache"] == "false"
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(document)}}],
                                        "usage": {"cost": 0.001, "prompt_tokens": 500, "completion_tokens": 100}})
    result = asyncio.run(analysis.analyze_sample(sample, [analysis.DEFAULT_MODEL], api_key="synthetic-key",
        transport=httpx.MockTransport(handler), research_binding=path))
    assert len(calls) == 1 and result["results"][0]["status"] == "unreviewed_analysis"
    assert result["schemaVersion"] == "fanvue.research-analysis-result.v1"
    assert result["partition"] == "development"


def test_cli_prepare_review_writes_private_new_files_without_credentials(tmp_path, monkeypatch):
    path, _, _ = files(tmp_path)
    monkeypatch.setattr(analysis, "load_dotenv", lambda *a, **kw: pytest.fail("unexpected credentials"))
    monkeypatch.setattr(analysis.httpx, "AsyncClient", lambda **kw: pytest.fail("unexpected client"))
    prepared_path, reviewed_path = tmp_path / "prepared.json", tmp_path / "reviewed.json"
    assert module.main(["--prepare", "--binding", str(path), "--output", str(prepared_path)]) == 0
    assert stat.S_IMODE(prepared_path.stat().st_mode) == 0o600
    assert module.main(["--review-non-explicit", "--binding", str(path), "--input", str(prepared_path),
                        "--output", str(reviewed_path)]) == 0
    assert json.loads(reviewed_path.read_text())["review"]["status"] == "approved_non_explicit"
    assert module.main(["--prepare", "--binding", str(path), "--output", str(prepared_path)]) == 2
