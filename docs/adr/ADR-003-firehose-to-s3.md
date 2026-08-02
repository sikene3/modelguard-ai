# ADR-003: Use Kinesis Data Firehose for prediction events

## Status
Accepted.

## Decision
The AWS API sends versioned newline-JSON prediction events to Firehose, which buffers GZIP objects
under physical UTC date/hour arrival-time prefixes. Exact model identity remains in each payload;
dynamic model-version partitioning is deferred. The producer creates one event ID and canonical
serialized line before bounded retries, so ambiguous at-least-once duplicates remain deduplicable.

## Rationale
This avoids one S3 object per request and avoids operating a custom consumer. It demonstrates a managed ingestion pattern while keeping the application simple.

## Consequences
Local mode requires a different event sink behind the same interface. Firehose delivery is
asynchronous, so monitoring scans partition overlap through a finalization grace and filters payload
event time. Producer acceptance, Firehose delivery, and S3 freshness are separate signals; the MVP
does not claim per-record delivery-lateness measurement. A successful `PutRecord` is producer
acceptance only, never evidence of delivery to S3.
