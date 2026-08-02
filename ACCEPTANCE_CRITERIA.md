# ModelGuard AI — Acceptance Criteria

## Global release gate

The MVP is portfolio-ready only when every required criterion below is evidenced by a command output, test, screenshot, report, or demo recording.

## Data and training

- [x] Dataset generation is deterministic for a fixed seed.
- [x] Schema and data-quality checks fail clearly on malformed data.
- [x] Training uses a single sklearn Pipeline including preprocessing.
- [x] Split is persisted before fitting; calibration is train-only; threshold is validation-only;
      the held-out test is evaluated once.
- [x] Calibration folds/method/ensemble, threshold grid/tie policy, reliability bins, and undefined
      metric serialization are explicit and deterministic rather than library defaults.
- [x] Average precision is compared with prevalence; calibration/cost evidence is reported.
- [x] Model bundle is immutable, checksummed, and versioned.
- [x] Baseline drift profile is generated from the training reference data.
- [x] Baseline includes frozen training-reference prediction-score and locked-decision distributions;
      these are not presented as training-performance evidence.
- [x] MLflow run records parameters, metrics, and artifacts locally.

## API

- [x] API starts with a valid model bundle.
- [x] Readiness fails with an invalid or missing bundle.
- [x] Prediction schema rejects invalid values.
- [x] Response includes request ID, model version, score, decision, and latency.
- [x] AWS access-mode tests prove health-check exemptions, prediction token enforcement over HTTPS,
      CIDR-only HTTP fallback behavior, and secret/log redaction.
- [x] No raw AWS credentials, tokens, or full environment dumps appear in logs.
- [x] API contract tests pass.
- [x] Prometheus metrics endpoint exposes request count, latency, predictions, and event-write failures.

## Event logging

- [x] Local event sink works without AWS.
- [x] AWS event sink uses Firehose and is mock-tested.
- [x] Event payload has retry-stable IDs, UTC event timestamp, and exact model/manifest/input-schema
      identities under a versioned event schema.
- [x] Firehose contract is newline JSON, GZIP, physical UTC date/hour prefix, and model identity in
      payload; dynamic model-version partitioning is explicitly deferred.
- [x] Producer rejection is logged/counted without crashing prediction and is never mislabeled as
      S3 delivery; Firehose delivery and S3 freshness use separate signals.
- [x] Local MVP events are atomic newline JSONL; closed-window reads are concurrency-safe.

## Drift monitoring

- [x] Repeated stationary traffic remains healthy at a sufficient sample size.
- [x] Injected drift reliably triggers warning/degraded status.
- [x] Small samples produce `insufficient_data`.
- [x] JSON report validates against a documented schema.
- [x] HTML report is generated and readable.
- [x] Monitor does not claim accuracy degradation without labels.
- [x] State transitions are deduplicated to prevent repeated alert spam.
- [x] UTC windows/finalization grace/frozen snapshots/target identity/dedup are tested, including
      exact `raw = rejected + outside_window + known_non_target + duplicate + accepted_target`.
- [x] Run/data-quality/drift/performance states are independent; performance is label-backed only.
- [x] Adequate-label performance state uses the versioned locked-threshold synthetic-cost delta
      policy; all public wording limits conclusions to the labeled subset and synthetic reference.
- [x] Report identity is independent of enumeration/file boundaries; immutable history, monotonic
      latest status, restart safety, and conditional alert deduplication are tested.

## Dashboard

- [x] Shows separate run/data-quality/drift/performance status and timestamp.
- [x] Shows active model identity separately from report target identity and accepted target volume.
- [x] Shows top drifting features and distributions.
- [x] Handles missing/stale reports honestly.
- [x] Loads from local storage and S3 through the same repository interface.

## Containers and local integration

Phase 07 images, Compose workflow, smoke/demo/E2E scripts, and zero-exception Trivy gate have run
successfully on a Docker-capable host. See `reports/phase-07.md`.

- [x] Containers run as non-root.
- [x] Images have health checks and minimal runtime dependencies.
- [x] `docker compose up --build` starts the local demo.
- [x] Smoke script sends traffic and verifies API/dashboard/monitor behavior.
- [x] Trivy reports no unaccepted critical findings.

## Terraform and AWS

- [ ] `terraform fmt -check`, `validate`, and Checkov pass with documented exceptions only.
- [ ] Separate least-privilege plan/deploy/execution/service/delivery/scheduler roles are scoped.
- [ ] Bootstrap owns OIDC roles and a mandatory permission boundary that demo deploy cannot alter;
      exact-subject trust and bounded `iam:PassRole` are evidenced.
- [ ] GitHub Actions uses OIDC, not stored AWS access keys.
- [ ] ALB requires explicit restricted CIDR; private tasks have no public IP.
- [ ] Two AZs, one documented NAT, S3 endpoint, state bootstrap, budget alert, alarm matrix, and
      guarded verified destroy are implemented.
- [ ] A confirmed, noncommitted human budget destination is required; drift SNS subscription remains
      optional, and budget alerts are documented as non-enforcing.
- [ ] Initial deployment uses a reviewed prerequisites plan with runtimes disabled, verifies exact
      image/model/token prerequisites, then uses a second reviewed digest-pinned activation plan.
- [ ] ECS deployment circuit breaker/rollback is enabled.
- [ ] Scheduled monitor task can read inputs and write reports.
- [ ] SNS notification is optional and configured without committing an email.
- [ ] CloudWatch logs and alarms exist; every alarm has a tested native-service or bounded EMF source,
      and scheduler submission is not treated as monitor completion.
- [ ] `terraform destroy` removes the demo environment without orphaned resources.

## CI/CD

- [ ] Pull requests run lint, typecheck, tests, and security scans.
- [ ] Infrastructure plan is reviewable and not auto-applied from untrusted PRs.
- [ ] Deployment workflow is manual or protected.
- [ ] Each deployable Git-SHA image is built/scanned once and promoted by digest without rebuild;
      actions/base images are pinned.
- [ ] Post-deploy smoke test runs.
- [ ] Failed deployment does not silently remain marked successful.

## Portfolio assets

- [ ] README contains architecture, quickstart, demo scenario, security, cost, and limitations.
- [ ] Architecture diagram is exported to PNG/SVG for LinkedIn/Upwork.
- [ ] 3–5 minute demo recording exists.
- [ ] At least four screenshots/GIFs exist.
- [ ] Case study explains the problem, trade-offs, implementation, evidence, and outcome.
- [ ] No active infrastructure or secrets remain after capture unless intentionally retained.
