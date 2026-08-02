"""UTC windows, frozen raw snapshots, exact identities, and exclusive record classification."""

from __future__ import annotations

import gzip
import json
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from modelguard.core.hashing import HashRecord, canonical_json_hash, sha256_bytes
from modelguard.core.serialization import StrictArtifactModel, canonical_json_bytes
from modelguard.inference.events import PredictionEventV1
from modelguard.monitoring.config import MonitoringConfig
from modelguard.monitoring.state import ensure_utc
from modelguard.training.bundle import ValidatedBundleMetadata


class EventIdentity(StrictArtifactModel):
    """The complete identity carried by every valid prediction event."""

    event_schema_version: str = Field(pattern=r"^modelguard\.prediction-event\.v[1-9][0-9]*$")
    model_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    bundle_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_schema_version: str = Field(pattern=r"^modelguard\.input\.v[1-9][0-9]*$")


class BaselineIdentity(StrictArtifactModel):
    """Baseline identity derived only from an exactly verified target manifest."""

    baseline_contract_version: Literal["modelguard.baseline-profile.v1"]
    baseline_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_schema_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_membership_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_row_count: int = Field(gt=0)


class MonitoringWindow(StrictArtifactModel):
    """One finalized UTC event-time half-open window."""

    semantics: Literal["event_time_utc_half_open_[start,end)"] = (
        "event_time_utc_half_open_[start,end)"
    )
    start: AwareDatetime
    end: AwareDatetime
    duration_seconds: int = Field(gt=0)
    finalization_grace_seconds: int = Field(ge=0)
    eligible_at: AwareDatetime
    delivery_lateness_metric: Literal["not_claimed"] = "not_claimed"

    @field_validator("start", "end", "eligible_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value, name="monitoring window timestamp")

    @model_validator(mode="after")
    def validate_window(self) -> MonitoringWindow:
        if self.end - self.start != timedelta(seconds=self.duration_seconds):
            raise ValueError("window duration does not reconcile")
        if self.eligible_at != self.end + timedelta(seconds=self.finalization_grace_seconds):
            raise ValueError("window eligibility does not match finalization grace")
        return self


def parse_utc_timestamp(value: str, *, name: str) -> datetime:
    """Parse a canonical ``Z`` timestamp for explicit CLI/test time control."""

    if not value.endswith("Z"):
        raise ValueError(f"{name} must be a canonical UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as error:
        raise ValueError(f"{name} must be a valid ISO 8601 UTC timestamp") from error
    return ensure_utc(parsed, name=name)


def default_window_end(as_of: datetime, config: MonitoringConfig) -> datetime:
    """Choose the latest whole-hour window whose grace has elapsed."""

    eligible_event_time = ensure_utc(as_of, name="as_of") - timedelta(
        seconds=config.finalization_grace_seconds
    )
    return eligible_event_time.replace(minute=0, second=0, microsecond=0)


def resolve_window(
    *,
    as_of: datetime,
    config: MonitoringConfig,
    window_end: datetime | None = None,
) -> MonitoringWindow:
    """Resolve and enforce a deterministic finalized monitoring window."""

    normalized_as_of = ensure_utc(as_of, name="as_of")
    end = (
        ensure_utc(window_end, name="window_end")
        if window_end is not None
        else default_window_end(normalized_as_of, config)
    )
    eligible_at = end + timedelta(seconds=config.finalization_grace_seconds)
    if normalized_as_of < eligible_at:
        raise ValueError("as_of must be at or after window end plus finalization grace")
    return MonitoringWindow(
        start=end - timedelta(seconds=config.window_seconds),
        end=end,
        duration_seconds=config.window_seconds,
        finalization_grace_seconds=config.finalization_grace_seconds,
        eligible_at=eligible_at,
    )


def identity_from_event(event: PredictionEventV1) -> EventIdentity:
    return EventIdentity(
        event_schema_version=event.event_schema_version,
        model_version=event.model_version,
        bundle_manifest_sha256=event.bundle_manifest_sha256,
        input_schema_version=event.input_schema_version,
    )


def target_identity_from_bundle(metadata: ValidatedBundleMetadata) -> EventIdentity:
    """Derive the exact v1 target event identity from verified bundle metadata."""

    return EventIdentity(
        event_schema_version="modelguard.prediction-event.v1",
        model_version=metadata.identity.model_version,
        bundle_manifest_sha256=metadata.identity.manifest_sha256,
        input_schema_version=metadata.input_schema.schema_version,
    )


def verify_target_identity(
    metadata: ValidatedBundleMetadata,
    target: EventIdentity,
) -> None:
    """Refuse a bundle that is not the run's already-snapshotted exact target."""

    derived = target_identity_from_bundle(metadata)
    if derived != target:
        raise ValueError("verified bundle identity does not match the snapshotted target identity")


def derive_baseline_identity(metadata: ValidatedBundleMetadata) -> BaselineIdentity:
    """Bind the baseline and input schema to the verified target manifest lineage."""

    return BaselineIdentity(
        baseline_contract_version=metadata.baseline.contract_version,
        baseline_profile_sha256=metadata.manifest.lineage.baseline_profile_hash.digest,
        input_schema_sha256=metadata.manifest.lineage.input_schema_hash.digest,
        training_membership_sha256=metadata.baseline.training_membership_hash.digest,
        training_row_count=metadata.baseline.training_row_count,
    )


@dataclass(frozen=True)
class FrozenRawSnapshot:
    """Raw logical JSONL records copied into memory at enumeration time."""

    records: tuple[bytes, ...]
    record_digests: tuple[str, ...]
    digest: HashRecord


class SnapshotReadError(RuntimeError):
    """A frozen local input could not be safely enumerated or read."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_non_finite(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is forbidden: {value}")


def parse_strict_json_record(raw: bytes) -> Any:
    """Parse one UTF-8 JSON value while rejecting duplicate keys and non-finite extensions."""

    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
        parse_constant=_reject_non_finite,
    )


def _semantic_record_digest(raw: bytes) -> str:
    try:
        parsed = parse_strict_json_record(raw)
    except (UnicodeError, ValueError):
        return sha256_bytes(raw)
    return sha256_bytes(canonical_json_bytes(parsed))


def _split_jsonl(payload: bytes) -> list[bytes]:
    if not payload:
        return []
    records = payload.split(b"\n")
    if records[-1] == b"":
        records.pop()
    return records


def freeze_raw_payloads(payloads: Sequence[bytes]) -> FrozenRawSnapshot:
    """Freeze already-enumerated JSONL payloads independent of their physical partitioning."""

    records = [record for payload in payloads for record in _split_jsonl(payload)]
    digests = tuple(_semantic_record_digest(record) for record in records)
    digest = canonical_json_hash(
        sorted(digests),
        ordering="logical record SHA-256 multiset ascending",
        exclusions=[
            "enumeration order",
            "storage object name",
            "file boundary",
            "enclosing-file hash",
            "bytes appended after snapshot enumeration",
        ],
    )
    return FrozenRawSnapshot(records=tuple(records), record_digests=digests, digest=digest)


def freeze_local_raw_snapshot(directory: Path) -> FrozenRawSnapshot:
    """Enumerate closed JSONL/GZIP objects and immediately freeze their logical records."""

    if not directory.exists():
        payloads: list[bytes] = []
    else:
        if directory.is_symlink() or not directory.is_dir():
            raise SnapshotReadError("input directory must be a non-symlink directory")
        candidates = sorted(
            [*directory.glob("*.jsonl"), *directory.glob("*.jsonl.gz")],
            key=lambda path: path.name,
        )
        payloads = []
        for path in candidates:
            if path.is_symlink() or not path.is_file():
                raise SnapshotReadError("input snapshot contains an unsafe entry")
            try:
                payload = path.read_bytes()
                if path.name.endswith(".gz"):
                    payload = gzip.decompress(payload)
            except (OSError, gzip.BadGzipFile, EOFError) as error:
                raise SnapshotReadError("could not freeze an input object") from error
            payloads.append(payload)
    return freeze_raw_payloads(payloads)


class RecordCounts(StrictArtifactModel):
    raw: int = Field(ge=0)
    rejected: int = Field(ge=0)
    outside_window: int = Field(ge=0)
    known_non_target: int = Field(ge=0)
    duplicate: int = Field(ge=0)
    accepted_target: int = Field(ge=0)

    @model_validator(mode="after")
    def reconcile(self) -> RecordCounts:
        classified = (
            self.rejected
            + self.outside_window
            + self.known_non_target
            + self.duplicate
            + self.accepted_target
        )
        if self.raw != classified:
            raise ValueError("raw record count does not reconcile to exclusive classifications")
        return self


class ClassificationFaults(StrictArtifactModel):
    parse_or_schema_failures: int = Field(ge=0)
    unknown_identity_records: int = Field(ge=0)
    conflicting_identity_records: int = Field(ge=0)
    conflicting_event_id_groups: int = Field(ge=0)
    conflicting_event_id_records: int = Field(ge=0)


class ObservedIdentity(StrictArtifactModel):
    identity: EventIdentity
    count: int = Field(gt=0)
    classification: Literal["target", "known_non_target", "unknown", "conflicting"]


class EventClassificationSummary(StrictArtifactModel):
    counts: RecordCounts
    faults: ClassificationFaults
    frozen_raw_snapshot_hash: HashRecord
    classified_record_multiset_hash: HashRecord
    observed_event_carried_identities: list[ObservedIdentity]
    max_accepted_event_timestamp: AwareDatetime | None


@dataclass(frozen=True)
class ClassifiedEvents:
    accepted_events: tuple[PredictionEventV1, ...]
    summary: EventClassificationSummary
    classified_record_digests: tuple[str, ...]


IdentityClassification = Literal["target", "known_non_target", "unknown", "conflicting"]


def _identity_key(identity: EventIdentity) -> str:
    return canonical_json_bytes(identity).decode("utf-8")


def _classify_identity(
    identity: EventIdentity,
    *,
    target: EventIdentity,
    known_non_targets: Sequence[EventIdentity],
) -> IdentityClassification:
    if identity == target:
        return "target"
    if identity in known_non_targets:
        return "known_non_target"
    registered = [target, *known_non_targets]
    durable_collision = any(
        identity.model_version == item.model_version
        or identity.bundle_manifest_sha256 == item.bundle_manifest_sha256
        for item in registered
    )
    return "conflicting" if durable_collision else "unknown"


def classify_snapshot(
    snapshot: FrozenRawSnapshot,
    *,
    window: MonitoringWindow,
    target: EventIdentity,
    known_non_targets: Sequence[EventIdentity] = (),
) -> ClassifiedEvents:
    """Classify exclusively, then deduplicate target candidates without input-order dependence."""

    if target in known_non_targets or len(
        {_identity_key(item) for item in known_non_targets}
    ) != len(known_non_targets):
        raise ValueError("known non-target identities must be unique and exclude the target")
    rejected = 0
    outside_window = 0
    known_non_target = 0
    duplicate = 0
    parse_failures = 0
    unknown_identity = 0
    conflicting_identity = 0
    conflicting_groups = 0
    conflicting_records = 0
    classified_digests: list[str] = []
    target_groups: dict[str, list[tuple[PredictionEventV1, str]]] = defaultdict(list)
    observed_counts: Counter[tuple[str, IdentityClassification]] = Counter()
    observed_identities: dict[str, EventIdentity] = {}

    for raw, raw_digest in zip(snapshot.records, snapshot.record_digests, strict=True):
        try:
            parsed = parse_strict_json_record(raw)
        except (UnicodeError, ValueError):
            rejected += 1
            parse_failures += 1
            classified_digests.append(f"rejected:{raw_digest}")
            continue
        if not isinstance(parsed, dict):
            rejected += 1
            parse_failures += 1
            classified_digests.append(f"rejected:{raw_digest}")
            continue
        try:
            event = PredictionEventV1.model_validate_json(canonical_json_bytes(parsed))
        except ValueError:
            rejected += 1
            parse_failures += 1
            classified_digests.append(f"rejected:{raw_digest}")
            continue

        if event.event_timestamp < window.start or event.event_timestamp >= window.end:
            outside_window += 1
            classified_digests.append(f"outside_window:{raw_digest}")
            continue
        identity = identity_from_event(event)
        identity_class = _classify_identity(
            identity,
            target=target,
            known_non_targets=known_non_targets,
        )
        key = _identity_key(identity)
        observed_identities[key] = identity
        observed_counts[(key, identity_class)] += 1
        if identity_class == "known_non_target":
            known_non_target += 1
            classified_digests.append(f"known_non_target:{raw_digest}")
            continue
        if identity_class == "unknown":
            rejected += 1
            unknown_identity += 1
            classified_digests.append(f"rejected:{raw_digest}")
            continue
        if identity_class == "conflicting":
            rejected += 1
            conflicting_identity += 1
            classified_digests.append(f"rejected:{raw_digest}")
            continue
        event_digest = sha256_bytes(canonical_json_bytes(event))
        target_groups[str(event.event_id)].append((event, event_digest))

    accepted: list[PredictionEventV1] = []
    for event_id in sorted(target_groups):
        group = target_groups[event_id]
        unique_digests = {digest for _, digest in group}
        if len(unique_digests) == 1:
            accepted.append(group[0][0])
            accepted_digest = group[0][1]
            classified_digests.append(f"accepted_target:{accepted_digest}")
            duplicate += len(group) - 1
            classified_digests.extend(f"duplicate:{accepted_digest}" for _ in range(len(group) - 1))
        else:
            conflicting_groups += 1
            conflicting_records += len(group)
            rejected += len(group)
            classified_digests.extend(f"rejected:{digest}" for _, digest in group)

    accepted.sort(
        key=lambda event: (str(event.event_id), sha256_bytes(canonical_json_bytes(event)))
    )
    observed = [
        ObservedIdentity(
            identity=observed_identities[key],
            count=count,
            classification=classification,
        )
        for (key, classification), count in sorted(
            observed_counts.items(), key=lambda item: (item[0][0], item[0][1])
        )
    ]
    counts = RecordCounts(
        raw=len(snapshot.records),
        rejected=rejected,
        outside_window=outside_window,
        known_non_target=known_non_target,
        duplicate=duplicate,
        accepted_target=len(accepted),
    )
    classified_hash = canonical_json_hash(
        sorted(classified_digests),
        ordering="classification then canonical logical-record digest ascending as a multiset",
        exclusions=["enumeration order", "storage object name", "file boundary"],
    )
    max_timestamp = max((event.event_timestamp for event in accepted), default=None)
    return ClassifiedEvents(
        accepted_events=tuple(accepted),
        summary=EventClassificationSummary(
            counts=counts,
            faults=ClassificationFaults(
                parse_or_schema_failures=parse_failures,
                unknown_identity_records=unknown_identity,
                conflicting_identity_records=conflicting_identity,
                conflicting_event_id_groups=conflicting_groups,
                conflicting_event_id_records=conflicting_records,
            ),
            frozen_raw_snapshot_hash=snapshot.digest,
            classified_record_multiset_hash=classified_hash,
            observed_event_carried_identities=observed,
            max_accepted_event_timestamp=max_timestamp,
        ),
        classified_record_digests=tuple(sorted(classified_digests)),
    )
