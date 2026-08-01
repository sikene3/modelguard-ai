# Phase 04 — Versioned Prediction Event Logging

## Recommended mode
GPT-5.6 Sol, XHigh.

## Objective
Record privacy-safe, versioned inference events through a pluggable event sink without making predictions depend on the sink availability.

## Required implementation
- Define a versioned schema with server-generated `event_id`, request ID, UTC event timestamp,
  `model_version`, `bundle_manifest_sha256`, `input_schema_version`, approved synthetic features,
  score, decision, and latency. Create one event ID/serialized record per successful prediction and
  reuse it unchanged across producer retries; a repeated client request is a new prediction/event.
- Local MVP sink uses one writer per file and atomic newline append, writing exactly one
  newline-terminated JSON object per successful sink write. Monitoring reads only a frozen snapshot
  or closed/rotated event file; Parquet is deferred.
- Firehose sink using an injected boto3 client.
- Configurable local/aws/disabled modes.
- Bounded connect/read timeout and retries; do not block requests indefinitely.
- Metrics and logs distinguish local persistence or Firehose producer acceptance from dropped/
  producer-failed events. A successful Firehose API call is never labeled S3 delivery. Emit the
  bounded event-write failure signal through the Phase 03 telemetry boundary in AWS mode.
- API integration.
- Unit tests with fake clients; no live AWS calls.
- Contract tests for event schema compatibility.
- Firehose contract: newline JSON records, GZIP output, physical UTC date/hour arrival-time prefixes,
  full model identity in the event (dynamic model partitioning is out of scope), and separate
  producer/Firehose-delivery/S3-freshness signals. The monitor scans partition overlap through grace
  and filters the payload event timestamp.

## Constraints
- No one-S3-object-per-prediction implementation.
- No raw card data, names, emails, IPs, tokens, or environment dumps.
- Prediction succeeds when event delivery fails; failure is observable.
- Do not implement Terraform/Firehose resources yet.

## Validation

```bash
uv run pytest tests/unit tests/contract tests/integration -q
make verify
```

Run the API in local mode, send multiple requests, and verify events are written and parseable.
