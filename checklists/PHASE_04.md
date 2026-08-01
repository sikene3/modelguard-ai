# Phase 04 Checklist

- [ ] Versioned event schema
- [ ] Retry-stable event/request IDs, UTC timestamp, and exact model/manifest/input-schema identity
- [ ] Local sink
- [ ] Firehose sink with fake client
- [ ] Failure does not fail prediction
- [ ] Producer acceptance/failure is not mislabeled as Firehose/S3 delivery
- [ ] Atomic single-writer local JSONL and frozen/closed-window read contract
- [ ] JSONL newline/GZIP/physical date-hour Firehose contract; model identity is payload-only
- [ ] Bounded timeout/retry and downstream freshness signals
- [ ] No sensitive fields

## Evidence

- Commands:
- Test results:
- Artifact paths:
- Commit:
- Residual risks:
