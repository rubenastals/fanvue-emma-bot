"""Build reviewed, private SFT examples and reserved evaluation cases offline.

No provider imports, credentials, network, training jobs, or production changes.
Approval covers the entire context and target in the exact reviewed input file.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIR = ROOT / "lab" / ".data" / "private-real-chats"
SCHEMA = "fanvue.chat-dataset-review.v1"
ALGORITHM = "reviewed-chat-dataset-v1"
HASH = r"^[0-9a-f]{64}$"
MESSAGE_ID = r"^message_\d{3}$"
CHAT_ID = r"^chat_\d{3}$"

# Owner-required exclusion: the input cannot replace or disable this guard.
# Store only fingerprints of normalized identifiers in this public repository.
EXCLUDED_ACCOUNT_SHA256 = "514a4f0207e84ff966cd08cc12dd7301b7a594491da14d07a13299ab92bf1664"
EXCLUDED_CONNECTION_SHA256 = "24f356e8e8924208bf49727d9f990908e92b8f96f461e38b16e3ffa54a76cded"
EXCLUDED_HANDLE_SHA256 = "4f0a7382a5e0b84d1e69cc0f8adc8458722d9e5db2a6ca80f6373883ae523443"


class DatasetError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def fail(code: str):
    raise DatasetError(code)


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            fail("invalid_timestamp")
        return result
    except (ValueError, TypeError):
        fail("invalid_timestamp")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Source(Strict):
    accountId: str = Field(min_length=1, max_length=128)
    connectionId: str = Field(min_length=1, max_length=128)
    handle: str = Field(min_length=1, max_length=100)
    classification: Literal["real_customer"]
    classificationBasis: str = Field(min_length=1, max_length=512)
    rawFile: str = Field(min_length=1, max_length=512)
    rawBytesSha256: str = Field(pattern=HASH)
    rawCanonicalSha256: str = Field(pattern=HASH)
    preparedBytesSha256: str = Field(pattern=HASH)


class ConversationBinding(Strict):
    id: str = Field(pattern=CHAT_ID)
    stableKey: str = Field(min_length=8, max_length=200)
    sourceConversationIndex: int = Field(ge=0, le=4)
    sourceMessageStart: int = Field(ge=0, le=99)


class Example(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    conversationId: str = Field(pattern=CHAT_ID)
    contextMessageIds: list[str] = Field(min_length=1, max_length=99)
    targetMessageIds: list[str] = Field(min_length=1, max_length=99)
    status: Literal["pending", "rejected", "approved_non_explicit"]
    textOnlySufficient: bool = False


class Split(Strict):
    seed: str = Field(min_length=1, max_length=128)
    holdoutPercent: int = Field(default=20, ge=1, le=50)


class Review(Strict):
    schemaVersion: Literal["fanvue.chat-dataset-review.v1"]
    purpose: Literal["non_explicit_response_training"]
    source: Source
    authorizationBasis: str = Field(min_length=1, max_length=512)
    reviewer: str = Field(min_length=1, max_length=128)
    reviewedAt: str = Field(min_length=1, max_length=50)
    approvalScope: Literal["entire_example_privacy_and_non_explicit"]
    split: Split
    conversations: list[ConversationBinding] = Field(min_length=1, max_length=5)
    examples: list[Example] = Field(max_length=500)


class Message(Strict):
    id: str = Field(pattern=MESSAGE_ID)
    role: Literal["fan", "creator", "unknown"]
    text: str | None
    minutesFromStart: float | int | None = Field(ge=0, allow_inf_nan=False)
    hasMedia: bool | None


class Conversation(Strict):
    id: str = Field(pattern=CHAT_ID)
    truncated: bool
    messages: list[Message] = Field(min_length=1, max_length=100)


class Prepared(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    schemaVersion: Literal["fanvue.chat-analysis-input.v1"]
    purpose: Literal["analysis_only_no_replies"]
    sourceSha256: str = Field(pattern=HASH)
    conversations: list[Conversation] = Field(min_length=1, max_length=5)


def no_symlinks(path: Path):
    if any(part.is_symlink() for part in [path, *path.parents]):
        fail("symlink_not_allowed")


def load_json(path: Path, limit: int) -> tuple[dict, bytes]:
    no_symlinks(path)
    try:
        with path.open("rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                fail("invalid_file")
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            fail("file_too_large")

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    fail("duplicate_json_key")
                result[key] = value
            return result

        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: fail("invalid_json"))
        if not isinstance(value, dict):
            fail("invalid_json")
        return value, raw
    except (OSError, UnicodeError, ValueError, RecursionError):
        fail("invalid_file")


def relative_json(base: Path, name: str) -> Path:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or path.suffix != ".json" or any(p.startswith(".") for p in path.parts):
        fail("invalid_source_path")
    result = base / path
    no_symlinks(result)
    if base.resolve() not in result.resolve().parents:
        fail("invalid_source_path")
    return result


def check_identity(source: Source):
    if (sha(normalized(source.accountId).encode()) == EXCLUDED_ACCOUNT_SHA256
            or sha(normalized(source.connectionId).encode()) == EXCLUDED_CONNECTION_SHA256
            or sha(normalized(source.handle).lstrip("@").encode()) == EXCLUDED_HANDLE_SHA256):
        fail("excluded_owner_test_source")
    if not all(normalized(v) for v in (source.accountId, source.connectionId, source.handle)):
        fail("invalid_identity")


def check_lineage(raw: dict, prepared: Prepared, bindings: list[ConversationBinding]):
    if raw.get("schemaVersion") != "fanvue.chat-export.v1" or type(raw.get("truncated")) is not bool:
        fail("invalid_raw_export")
    raw_chats = raw.get("conversations")
    if not isinstance(raw_chats, list) or not 1 <= len(raw_chats) <= 5:
        fail("invalid_raw_export")
    chats = {c.id: c for c in prepared.conversations}
    if len(chats) != len(prepared.conversations) or len({c.id for c in bindings}) != len(bindings) or set(chats) != {c.id for c in bindings}:
        fail("conversation_binding_mismatch")
    for binding in bindings:
        clean_key = unicodedata.normalize("NFKC", binding.stableKey).strip()
        if re.fullmatch(CHAT_ID, clean_key.casefold()) or not clean_key:
            fail("unstable_conversation_key")
        chat = chats[binding.id]
        try:
            original = raw_chats[binding.sourceConversationIndex]
            messages = original["messages"]
            if not isinstance(messages, list) or len(messages) > 100 or type(original.get("truncated")) is not bool:
                fail("invalid_raw_export")
            selected = messages[binding.sourceMessageStart:binding.sourceMessageStart + len(chat.messages)]
            if len(selected) != len(chat.messages):
                fail("source_range_mismatch")
            times = [timestamp(m.get("sentAt")) for m in selected]
            known = [t for t in times if t is not None]
            if known != sorted(known):
                fail("nonchronological_source")
            anchor = min(known) if known else None
            if chat.truncated != (original["truncated"] or len(selected) < len(messages)):
                fail("source_facts_changed")
            for index, (before, after, time) in enumerate(zip(selected, chat.messages, times), 1):
                minutes = round((time - anchor).total_seconds() / 60, 2) if time and anchor else None
                if (after.id != f"message_{index:03d}" or before.get("role") != after.role
                        or "hasMedia" not in before or before["hasMedia"] != after.hasMedia
                        or (before["hasMedia"] is not None and type(before["hasMedia"]) is not bool)
                        or minutes != after.minutesFromStart):
                    fail("source_facts_changed")
                if "text" not in before or (before["text"] is not None and not isinstance(before["text"], str)):
                    fail("invalid_raw_export")
                if not (before["text"] or "").strip() and (after.text or "").strip():
                    fail("source_text_presence_changed")
                if after.text is not None and len(after.text.encode("utf-8")) > 16 * 1024:
                    fail("message_too_large")
        except (KeyError, IndexError, TypeError, AttributeError):
            fail("invalid_source_range")


def normalized_messages(messages: list[dict]) -> list[dict]:
    return [{"role": m["role"], "content": " ".join(unicodedata.normalize("NFKC", m["content"]).split())}
            for m in messages]


def merge_messages(messages: list[Message]) -> list[dict]:
    result = []
    for message in messages:
        if message.role not in ("fan", "creator") or not isinstance(message.text, str) or not message.text.strip():
            fail("unusable_message")
        role = "user" if message.role == "fan" else "assistant"
        if result and result[-1]["role"] == role:
            result[-1]["content"] += "\n\n" + message.text
        else:
            result.append({"role": role, "content": message.text})
    return result


def build_example(example: Example, chat: Conversation, *, next_source_role: str | None = None) -> dict:
    if not example.textOnlySufficient:
        fail("text_only_review_required")
    index = {message.id: i for i, message in enumerate(chat.messages)}
    ids = example.contextMessageIds + example.targetMessageIds
    if len(set(ids)) != len(ids) or any(i not in index for i in ids):
        fail("invalid_example_messages")
    positions = [index[i] for i in ids]
    if positions != list(range(positions[0], positions[0] + len(positions))):
        fail("noncontiguous_or_future_context")
    context = [chat.messages[index[i]] for i in example.contextMessageIds]
    target = [chat.messages[index[i]] for i in example.targetMessageIds]
    if context[0].role != "fan" or context[-1].role != "fan" or any(m.role != "creator" for m in target):
        fail("invalid_role_boundary")
    next_index = positions[-1] + 1
    following_role = chat.messages[next_index].role if next_index < len(chat.messages) else next_source_role
    if following_role == "creator":
        fail("incomplete_creator_turn")
    inputs, targets = merge_messages(context), merge_messages(target)
    messages = inputs + targets
    fingerprint = sha(canonical(normalized_messages(messages)))
    return {"id": "example_" + fingerprint, "messages": messages, "inputs": inputs,
            "target": targets[0], "fingerprint": fingerprint,
            "contextFingerprint": sha(canonical(normalized_messages(inputs)))}


def build_dataset(prepared_path: Path, review_path: Path) -> dict:
    review_value, review_bytes = load_json(review_path, 256 * 1024)
    try:
        review = Review.model_validate(review_value)
    except ValidationError:
        fail("invalid_review")
    check_identity(review.source)  # Must precede reading raw or prepared content.
    timestamp(review.reviewedAt)
    if len({e.id for e in review.examples}) != len(review.examples):
        fail("duplicate_review_example_id")
    approved = [e for e in review.examples if e.status == "approved_non_explicit"]
    if not approved:
        fail("no_approved_examples")
    raw_path = relative_json(review_path.absolute().parent, review.source.rawFile)
    raw, raw_bytes = load_json(raw_path, 4 * 1024 * 1024)
    if sha(raw_bytes) != review.source.rawBytesSha256:
        fail("raw_bytes_hash_mismatch")
    if sha(canonical(raw)) != review.source.rawCanonicalSha256:
        fail("raw_canonical_hash_mismatch")
    prepared_value, prepared_bytes = load_json(prepared_path, 4 * 1024 * 1024)
    if sha(prepared_bytes) != review.source.preparedBytesSha256:
        fail("prepared_review_hash_mismatch")
    try:
        prepared = Prepared.model_validate(prepared_value)
    except ValidationError:
        fail("invalid_prepared")
    if prepared.sourceSha256 != review.source.rawCanonicalSha256:
        fail("prepared_source_hash_mismatch")
    payload = {"purpose": prepared.purpose, "conversations": [c.model_dump() for c in prepared.conversations]}
    if len(canonical(payload)) > 64 * 1024:
        fail("prepared_payload_too_large")
    check_lineage(raw, prepared, review.conversations)
    chats = {c.id: c for c in prepared.conversations}
    keys = {c.id: unicodedata.normalize("NFKC", c.stableKey).strip() for c in review.conversations}
    next_roles = {}
    for binding in review.conversations:
        original_messages = raw["conversations"][binding.sourceConversationIndex]["messages"]
        end = binding.sourceMessageStart + len(chats[binding.id].messages)
        if end < len(original_messages):
            following = original_messages[end]
            if not isinstance(following, dict) or following.get("role") not in ("fan", "creator", "unknown"):
                fail("invalid_raw_export")
            next_roles[binding.id] = following["role"]
    parent = {key: key for key in keys.values()}

    def root(key):
        while parent[key] != key:
            key = parent[key]
        return key

    def union(a, b):
        first, second = sorted((root(a), root(b)))
        parent[second] = first

    # Two windows of the same known source conversation cannot split, even if
    # the operator accidentally assigned different stable keys/local IDs.
    source_keys = {}
    for binding in review.conversations:
        key = keys[binding.id]
        if binding.sourceConversationIndex in source_keys:
            union(key, source_keys[binding.sourceConversationIndex])
        source_keys[binding.sourceConversationIndex] = key

    # Duplicate histories or identical contexts are grouped before splitting.
    transcript_keys, context_keys, rows = {}, {}, []
    for example in sorted(approved, key=lambda e: e.id):
        if example.conversationId not in chats:
            fail("unknown_conversation")
        chat, key = chats[example.conversationId], keys[example.conversationId]
        row = build_example(example, chat, next_source_role=next_roles.get(example.conversationId))
        transcript = sha(canonical([{"role": m.role, "text": " ".join(unicodedata.normalize("NFKC", m.text or "").split())}
                                    for m in chat.messages]))
        for lookup, fingerprint in ((transcript_keys, transcript), (context_keys, row["contextFingerprint"])):
            if fingerprint in lookup:
                union(key, lookup[fingerprint])
            lookup[fingerprint] = key
        rows.append({**row, "key": key})
    train, evaluation, allocations, seen = [], [], [], set()
    for row in sorted(rows, key=lambda r: (r["fingerprint"], r["key"])):
        if row["fingerprint"] in seen:
            continue
        seen.add(row["fingerprint"])
        group = root(row["key"])
        bucket = int(sha(canonical([review.split.seed, normalized(review.source.accountId), group])), 16) % 100
        partition = "evaluation" if bucket < review.split.holdoutPercent else "train"
        group_ref = sha(canonical([normalized(review.source.accountId), group]))
        allocations.append({"exampleId": row["id"], "conversationGroup": group_ref, "partition": partition})
        if partition == "train":
            train.append({"messages": row["messages"], "targetMessageIndex": len(row["messages"]) - 1})
        else:
            evaluation.append({"id": row["id"], "inputMessages": row["inputs"], "referenceResponse": row["target"]})
    counts = Counter(e.status for e in review.examples)
    manifest = {
        "schemaVersion": "fanvue.chat-dataset-manifest.v1", "algorithm": ALGORITHM,
        "sourceBytesSha256": sha(raw_bytes), "sourceCanonicalSha256": sha(canonical(raw)),
        "preparedBytesSha256": sha(prepared_bytes), "reviewBytesSha256": sha(review_bytes),
        "approvalScope": review.approvalScope, "exclusionGuard": "owner_test_account_v1",
        "split": {**review.split.model_dump(), "unit": "conversation_duplicate_group"},
        "counts": {"reviewedExamples": len(review.examples), "approvedExamples": len(approved),
                   "pendingExamples": counts["pending"], "rejectedExamples": counts["rejected"],
                   "duplicatesRemoved": len(rows) - len(seen), "trainExamples": len(train),
                   "evaluationExamples": len(evaluation), "conversationGroups": len({a["conversationGroup"] for a in allocations})},
        "readiness": "pilot" if train and evaluation else "insufficient",
        "readyForTraining": False, "trainingJobStarted": False,
        "allocations": allocations,
        "limitations": [
            "Identity, stable conversation keys, permissions and content approval are operator attestations; hashes verify integrity.",
            "Leakage checks cover this bundle and normalized exact histories/contexts/examples, not other exports or semantic paraphrases.",
            "A single customer does not measure generalization to other accounts; no revenue or human-authorship claim is made.",
            "This exporter creates a pilot corpus, not evidence of sufficient volume, quality, a selected training model, or a completed training run.",
            "An empty partition is reported without moving the seed; add independently reviewed conversations before training.",
        ],
    }
    return {"train": train, "evaluation": evaluation, "manifest": manifest}


def write_dataset(destination: Path, result: dict) -> Path:
    destination = destination.expanduser().absolute()
    no_symlinks(destination)
    resolved = destination.resolve()
    if resolved == ROOT or (ROOT in resolved.parents and PRIVATE_DIR.resolve() not in resolved.parents):
        fail("unsafe_output_directory")
    if destination.exists():
        fail("output_exists")
    files = {"train.jsonl": b"".join(canonical(row) + b"\n" for row in result["train"]),
             "evaluation.jsonl": b"".join(canonical(row) + b"\n" for row in result["evaluation"])}
    manifest = {**result["manifest"], "files": {name: {"sha256": sha(data), "bytes": len(data)} for name, data in files.items()}}
    files["manifest.json"] = canonical(manifest) + b"\n"
    created = False
    try:
        missing, current = [], destination.parent
        while not current.exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            directory.mkdir(mode=0o700)
        destination.mkdir(mode=0o700)  # Exclusive directory creation; never replace an existing bundle.
        created = True
        for name, data in files.items():
            fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
    except OSError:
        if created:
            shutil.rmtree(destination)
        fail("output_failed")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_dataset(args.prepared, args.review)
        output = write_dataset(args.output_dir, result)
        print(json.dumps({"status": "saved", "outputDirectory": str(output),
                          "readiness": result["manifest"]["readiness"],
                          "readyForTraining": result["manifest"]["readyForTraining"],
                          **result["manifest"]["counts"]}), flush=True)
        return 0
    except DatasetError as error:
        print(json.dumps({"status": "error", "code": error.code}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
