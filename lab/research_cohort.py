"""Validate private research provenance; no network, model, chat text, or training.

Evidence is operator-attested and file-integrity checked. This does not verify
its financial truth independently or establish permission to train a model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIR = ROOT / "lab" / ".data" / "private-real-chats"
INPUT_SCHEMA = "fanvue.research-cohort-input.v1"
OUTPUT_SCHEMA = "fanvue.research-cohort.v1"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_EVIDENCE_BYTES = 16 * 1024 * 1024


class CohortError(Exception):
    """Only fixed error codes may cross the CLI boundary."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("timestamp required") from None
    if parsed.tzinfo is None:
        raise ValueError("timezone required")
    return parsed


def normalize_identifier(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def normalize_handle(value: str) -> str:
    return normalize_identifier(value).removeprefix("@").strip()


class Identity(StrictModel):
    accountId: str = Field(min_length=1, max_length=128)
    connectionId: str | None = Field(default=None, min_length=1, max_length=128)
    handle: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("accountId", "connectionId", "handle")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not normalize_identifier(value).removeprefix("@").strip():
            raise ValueError("empty identifier")
        return value


class Exclusion(StrictModel):
    accountId: str | None = Field(default=None, min_length=1, max_length=128)
    connectionId: str | None = Field(default=None, min_length=1, max_length=128)
    handle: str | None = Field(default=None, min_length=1, max_length=128)
    reason: Literal["owner_declared_test", "internal_test", "do_not_use"]

    @model_validator(mode="after")
    def identifier_required(self):
        values = (self.accountId, self.connectionId, self.handle)
        if not any(values) or any(v is not None and not normalize_identifier(v).removeprefix("@").strip() for v in values):
            raise ValueError("exclusion identifier required")
        return self


class Evidence(StrictModel):
    source: Literal["fanvue_api", "fanvue_verified_export"]
    file: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verifiedAt: str
    recordLocator: str = Field(min_length=1, max_length=256)

    @field_validator("verifiedAt")
    @classmethod
    def timestamp(cls, value):
        _time(value)
        return value


class Revenue(Evidence):
    accountId: str = Field(min_length=1, max_length=128)
    metric: Literal["gross_earnings", "net_earnings"]
    amountMinor: int
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    periodStart: str
    periodEnd: str

    @model_validator(mode="after")
    def period(self):
        if _time(self.periodEnd) <= _time(self.periodStart):
            raise ValueError("invalid revenue period")
        return self


class Purchase(Evidence):
    accountId: str = Field(min_length=1, max_length=128)
    conversationKey: str = Field(min_length=1, max_length=128)
    eventId: str = Field(min_length=1, max_length=128)
    kind: Literal["purchase", "refund"]
    amountMinor: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    occurredAt: str

    @field_validator("occurredAt")
    @classmethod
    def timestamp(cls, value):
        _time(value)
        return value


class Conversation(StrictModel):
    conversationKey: str = Field(min_length=1, max_length=128)
    file: str = Field(min_length=1, max_length=512)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    firstMessageId: str = Field(min_length=1, max_length=128)
    lastMessageId: str = Field(min_length=1, max_length=128)
    messageCount: int = Field(ge=1, le=10000)
    rangeStart: str
    rangeEnd: str
    truncated: bool
    review: Literal["not_reviewed", "approved_non_explicit", "excluded"] = "not_reviewed"
    purchaseEvidence: list[Purchase] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def period(self):
        if _time(self.rangeEnd) < _time(self.rangeStart):
            raise ValueError("invalid conversation range")
        return self


class Account(StrictModel):
    accountKey: str = Field(min_length=1, max_length=128)
    identity: Identity
    classification: Literal["test", "real_verified", "unknown"]
    classificationBasis: str = Field(min_length=1, max_length=256)
    observedAt: str
    active: bool | None
    revenueEvidence: list[Revenue] = Field(default_factory=list, max_length=20)
    conversations: list[Conversation] = Field(default_factory=list, max_length=100)

    @field_validator("observedAt")
    @classmethod
    def timestamp(cls, value):
        _time(value)
        return value


class Authorizations(StrictModel):
    analysis: Literal["authorized", "denied", "not_recorded"] = "not_recorded"
    evaluation: Literal["authorized", "denied", "not_recorded"] = "not_recorded"
    training: Literal["authorized", "denied", "not_recorded"] = "not_recorded"
    basis: str = Field(min_length=1, max_length=512)


class Split(StrictModel):
    unit: Literal["account", "conversation"] = "account"
    seed: str = Field(min_length=1, max_length=128)
    holdoutPercent: int = Field(default=20, ge=1, le=50)


class Manifest(StrictModel):
    schemaVersion: Literal["fanvue.research-cohort-input.v1"]
    purpose: Literal["offline_conversation_research"]
    authorizations: Authorizations
    exclusions: list[Exclusion] = Field(default_factory=list, max_length=200)
    split: Split
    accounts: list[Account] = Field(min_length=1, max_length=200)


def _private_path(path: Path) -> Path:
    absolute = path.expanduser().absolute()
    try:
        resolved = absolute.resolve()
    except (OSError, RuntimeError):
        raise CohortError("unsafe_path") from None
    if resolved == ROOT or (ROOT in resolved.parents and PRIVATE_DIR.resolve() not in resolved.parents):
        raise CohortError("private_path_required")
    if absolute.is_symlink() or absolute != resolved:
        raise CohortError("symlink_or_noncanonical_path")
    return resolved


def _hash_evidence(base: Path, name: str, expected: str) -> None:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise CohortError("evidence_path_outside_manifest")
    target = base / relative
    try:
        if target.is_symlink() or target.resolve() != target or base not in target.parents:
            raise CohortError("unsafe_evidence_path")
        with target.open("rb") as file:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_EVIDENCE_BYTES:
                raise CohortError("invalid_evidence_file")
            hasher, total = hashlib.sha256(), 0
            while chunk := file.read(65536):
                total += len(chunk)
                if total > MAX_EVIDENCE_BYTES:
                    raise CohortError("invalid_evidence_file")
                hasher.update(chunk)
            digest = hasher.hexdigest()
    except (OSError, RuntimeError):
        raise CohortError("evidence_unavailable") from None
    if digest != expected:
        raise CohortError("evidence_hash_mismatch")


def _matches(identity: Identity, exclusion: Exclusion) -> bool:
    for field in ("accountId", "connectionId", "handle"):
        actual, blocked = getattr(identity, field), getattr(exclusion, field)
        normalizer = normalize_handle if field == "handle" else normalize_identifier
        if actual is not None and blocked is not None and normalizer(actual) == normalizer(blocked):
            return True
    return False


def _partition(split: Split, account_id: str, conversation_key: str) -> str:
    identity = normalize_identifier(account_id)
    group = [split.seed, split.unit, identity]
    if split.unit == "conversation":
        group.append(conversation_key)
    value = int.from_bytes(hashlib.sha256(json.dumps(group, separators=(",", ":")).encode()).digest()[:8], "big")
    return "holdout" if value % 100 < split.holdoutPercent else "development"


def compile_cohort(value: dict, *, evidence_directory: Path) -> dict:
    try:
        if len(_json_bytes(value)) > MAX_MANIFEST_BYTES:
            raise CohortError("manifest_too_large")
        manifest = Manifest.model_validate(value)
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise CohortError("invalid_manifest") from None
    base = evidence_directory.resolve()
    account_keys = [a.accountKey for a in manifest.accounts]
    if len(set(account_keys)) != len(account_keys):
        raise CohortError("duplicate_account_key")
    # A block on one connection/handle blocks every representation of that account.
    blocked = {normalize_identifier(a.identity.accountId) for a in manifest.accounts
               if a.classification == "test" or any(_matches(a.identity, x) for x in manifest.exclusions)}
    output, counts, source_partitions, seen_events = [], Counter(), {}, set()
    for account in manifest.accounts:
        account_id = normalize_identifier(account.identity.accountId)
        reasons = []
        if account_id in blocked:
            status, reasons = "excluded", ["test_or_explicit_exclusion"]
        elif account.active is False:
            status, reasons = "excluded", ["inactive_account"]
        else:
            if account.classification != "real_verified":
                reasons.append("real_customer_not_verified")
            if account.active is not True:
                reasons.append("active_status_unknown")
            if not account.revenueEvidence:
                reasons.append("revenue_evidence_missing")
            for revenue in account.revenueEvidence:
                if normalize_identifier(revenue.accountId) != account_id:
                    raise CohortError("revenue_account_mismatch")
                _hash_evidence(base, revenue.file, revenue.sha256)
            if account.revenueEvidence and not any(r.amountMinor > 0 for r in account.revenueEvidence):
                reasons.append("no_positive_revenue_in_verified_period")
            status = "pending_evidence" if reasons else "eligible"
        conversations, seen_keys = [], set()
        # Excluded accounts retain references but their files are never opened.
        for conversation in account.conversations:
            if conversation.conversationKey in seen_keys:
                raise CohortError("duplicate_conversation_key")
            seen_keys.add(conversation.conversationKey)
            record = conversation.model_dump()
            ready = status == "eligible" and conversation.review != "excluded"
            partition = _partition(manifest.split, account.identity.accountId, conversation.conversationKey) if ready else None
            if ready:
                _hash_evidence(base, conversation.file, conversation.sha256)
                for purchase in conversation.purchaseEvidence:
                    if normalize_identifier(purchase.accountId) != account_id or purchase.conversationKey != conversation.conversationKey:
                        raise CohortError("purchase_attribution_mismatch")
                    event_key = (account_id, purchase.eventId, purchase.kind)
                    if event_key in seen_events:
                        raise CohortError("duplicate_purchase_event")
                    seen_events.add(event_key)
                    _hash_evidence(base, purchase.file, purchase.sha256)
                # A source conversation must not be reused across partitions.
                source_key = (conversation.sha256, conversation.conversationKey)
                if source_key in source_partitions and source_partitions[source_key] != partition:
                    raise CohortError("source_reused_across_partitions")
                source_partitions[source_key] = partition
            record.update(
                partition=partition,
                analysisReadiness="ready_for_review" if ready and manifest.authorizations.analysis == "authorized" else "blocked",
                evaluationReadiness="ready_for_review" if ready and conversation.review == "approved_non_explicit" and manifest.authorizations.evaluation == "authorized" else "blocked",
                trainingReadiness="unsupported",
                commercialOutcome="verified_events_recorded" if ready and conversation.purchaseEvidence else "unknown",
                purchaseCausalityEstablished=False,
            )
            conversations.append(record)
        counts[status] += 1
        output.append({**account.model_dump(exclude={"conversations"}), "eligibility": status,
                       "eligibilityReasons": reasons, "revenueKnown": bool(account.revenueEvidence) if status != "excluded" else None,
                       "conversations": conversations})
    return {
        "schemaVersion": OUTPUT_SCHEMA, "createdAt": datetime.now(timezone.utc).isoformat(),
        "purpose": manifest.purpose, "inputCanonicalSha256": hashlib.sha256(_json_bytes(value)).hexdigest(),
        "authorizations": manifest.authorizations.model_dump(), "exclusions": [x.model_dump() for x in manifest.exclusions],
        "split": manifest.split.model_dump(), "accounts": output,
        "summary": {"accounts": len(output), **{k: counts[k] for k in ("eligible", "pending_evidence", "excluded")}},
        "limitations": [
            "Evidence source, account classification and permissions are operator attestations; file hashes verify integrity, not financial truth or legal rights.",
            "Positive account revenue does not prove that any selected message caused a purchase.",
            "Missing purchase events mean unknown outcome, not a failed sale or zero income.",
            "Only metadata is emitted; no chat text, network call, model training or live prompt change occurs.",
            "A small cohort may leave a partition empty; preserve the seed and add accounts instead of choosing a seed after seeing results.",
        ] + (["Conversation split does not prevent customer/account information leaking across partitions; use account split for the main evaluation."] if manifest.split.unit == "conversation" else []),
        "trainingExportAllowed": False,
    }


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_manifest(path: Path) -> dict:
    source = _private_path(path)
    try:
        with source.open("rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise CohortError("invalid_manifest_file")
            raw = file.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise CohortError("manifest_too_large")
        value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise CohortError("invalid_manifest_file") from None


def write_private(path: Path, value: dict) -> None:
    destination = _private_path(path)
    if destination.exists():
        raise CohortError("output_exists")
    try:
        missing, current = [], destination.parent
        while not current.exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            directory.mkdir(mode=0o700)
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(_json_bytes(value) + b"\n")
    except OSError:
        raise CohortError("output_failed") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private metadata-only research cohort; no training or model calls.")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        source = _private_path(args.input)
        result = compile_cohort(read_manifest(source), evidence_directory=source.parent)
        write_private(args.output, result)
    except CohortError as exc:
        print(json.dumps({"status": "error", "errorCode": exc.code}), flush=True)
        return 2
    print(json.dumps({"status": "saved", **result["summary"], "trainingExportAllowed": False}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
