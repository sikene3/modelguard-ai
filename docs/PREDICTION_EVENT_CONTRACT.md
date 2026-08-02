# Prediction Event Contract

Phase 04 constructs one privacy-safe, versioned event for every successfully scored prediction and
passes it to the configured sink. Event handling is deliberately fail-open: a sink timeout, local
write failure, disabled drop, or Firehose producer failure is observable but does not change the
prediction response.

## Versioned payload

The runtime contract is `modelguard.inference.events.PredictionEventV1`; the portable JSON Schema is
[`contracts/prediction-event-v1.schema.json`](../contracts/prediction-event-v1.schema.json), and the
frozen compatibility example is
[`tests/fixtures/contracts/prediction-event-v1.json`](../tests/fixtures/contracts/prediction-event-v1.json).

Every record contains exactly these top-level fields:

- `event_schema_version`: currently `modelguard.prediction-event.v1`.
- `event_id`: a new server-generated UUID for this scoring operation.
- `request_id`: the server-generated API correlation UUID.
- `event_timestamp`: the UTC time at which scoring completed, serialized with `Z`.
- `model_version`, `bundle_manifest_sha256`, and `input_schema_version`: the complete verified model
  and input-contract identity captured by the API process at startup.
- `features`: only the nine strict synthetic Phase 02 fields needed for drift monitoring.
- `score` and locked-threshold `decision`.
- `latency_ms`: non-negative scoring latency, frozen once and reused in the HTTP response and event.

Extra fields are forbidden at both event and feature levels. The approved payload contains no card
number, cardholder name, email address, IP address, credential, token, authorization header, request
metadata, environment dump, raw body, or real payment data.

The event UUID and canonical serialized bytes are created once before the sink is called. Every
Firehose retry submits those same bytes. An ambiguous producer response can therefore create a
duplicate downstream record, but duplicates retain the same `event_id` for Phase 05 reconciliation.
A new HTTP request is a new scoring operation and always creates a new event, even if its feature
values match an earlier request. This is an at-least-once producer contract, not an exactly-once
delivery claim.

## Local sink

Local mode writes under `LOCAL_EVENT_DIR`, which defaults to `artifacts/predictions/`.

- Each sink instance creates a unique `*.jsonl.open` file with mode `0600` and owns its sole writer.
- A record is canonical JSON plus exactly one trailing newline. The sink uses one `O_APPEND` write
  under a serialized worker and calls `fsync` before reporting `local_persisted`.
- It never retries a local append, because blindly retrying an ambiguous append could create a
  duplicate line.
- Rotation closes and syncs the writer, atomically publishes a non-overwriting hard link with the
  final `*.jsonl` name, and removes the active name. Closed files are never reopened by the sink.
- `freeze_local_event_snapshot()` freezes a sorted tuple of closed `*.jsonl` files and excludes all
  active `*.open` files. Phase 05 may read only that frozen enumeration or another already
  closed/rotated file. It must never tail an active writer file.

Parquet and multi-process sharing of one event file are intentionally deferred. Multiple API
processes would use separate unique files; the current `make api` command runs one Uvicorn worker.

## AWS producer and physical S3 contract

`EVENT_SINK=aws` creates the Firehose client lazily on the first event write unless a fake/injected
client is supplied, so application construction and model readiness do not perform credential or
producer work. The SDK client has explicit connect/read timeouts, disables hidden SDK retries, and
the application performs a small configured number of retries with bounded exponential delays. Unit
and integration tests use injected fake clients and make no AWS calls. If the request-level event
deadline expires, the API returns without waiting for the underlying thread; a one-operation gate
prevents later events from building an unbounded producer queue while that call finishes.

The later Phase 08 Firehose resource must preserve this frozen physical contract:

- input record: one newline-terminated JSON object;
- S3 compression: `GZIP`;
- physical arrival-time prefix:
  `predictions/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/`;
- timestamp prefix evaluation in UTC;
- complete model identity in every payload;
- no dynamic model-version partitioning.

Firehose buffers records into S3 objects. The API never writes one object per prediction and never
calls S3 for event persistence.

## Signal semantics

Producer acknowledgement, downstream delivery, and usable-object freshness answer different
questions and must remain separate:

| Boundary | Meaning | Phase 04 or later signal |
| --- | --- | --- |
| API/local writer | A complete line was appended and synced locally | `local_persisted` |
| API/Firehose producer | `PutRecord` returned a non-empty `RecordId` | `firehose_accepted` / `FirehoseProducerAccepted` |
| Firehose delivery | Firehose reports delivery to its S3 destination | Native Firehose delivery metrics and errors, configured in Phase 08 |
| S3 freshness | Expected physical UTC prefixes contain sufficiently recent closed objects | Separate monitor/CloudWatch freshness signal, implemented in Phases 05/08 |

`firehose_accepted` never means “delivered to S3.” Disabled events, timeouts, local failures, and
Firehose producer failures have separate Prometheus outcome labels and fixed-name AWS EMF signals.
AWS producer failures also pass through the Phase 03 `ErrorKind.EVENT_SINK` telemetry boundary.
Server-generated request/event IDs and model identity may be safe correlation log context; feature
values are never logged. None of those values is a metric dimension.

## Monitoring handoff

Because the S3 path is based on Firehose arrival time rather than payload event time, Phase 05 now
freezes an injected local or version-pinned S3 input enumeration, parses/validates events, and
applies the authoritative half-open payload filter
`event_timestamp in [window_start, window_end)`. Grace delays finalization; it is not a claim that
individual row lateness was measured. The exact monitoring behavior is documented in
`docs/MONITORING_CONTRACT.md`; Terraform, Firehose resources, and CloudWatch alarms remain later
phases.
