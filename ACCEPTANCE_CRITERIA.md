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
- [x] Trivy reports no unaccepted HIGH or CRITICAL findings for exact immutable image IDs.

## Terraform and AWS

- [x] `terraform fmt -check`, `validate`, and Checkov pass with documented exceptions only.
- [x] Separate least-privilege plan/deploy/execution/service/delivery/scheduler roles are scoped.
- [x] Bootstrap owns OIDC roles and a mandatory permission boundary that demo deploy cannot alter;
      customized legacy/immutable subjects bind exact repository, ref, protected environment,
      workflow, and audience; bounded `iam:PassRole` is evidenced.
- [x] GitHub Actions uses customized exact-subject OIDC, not stored AWS access keys; IAM is updated
      before the matching repository subject template, and live claim exchange remains a Phase 10
      execution check.
- [x] actionlint, ShellCheck, Checkov, Gitleaks, and Trivy share one repository-owned fail-closed
      local/CI gate and one exact version/checksum-or-digest lock; missing tools and scanner nonzero
      exits fail the release gate.
- [x] Release scans cover every workflow, tracked shell plus embedded workflow Bash, Terraform,
      Dockerfiles, GitHub Actions, full Git history, the current worktree, repository files/config,
      and the exact build-produced image identities.
- [x] Security jobs have no AWS identity or deployment authority; supported scanner evidence is
      sanitized SARIF, and no raw secret match, cache, database, state, or saved plan is uploaded.
- [x] ALB requires explicit restricted CIDR; private tasks have no public IP.
- [x] Two AZs, one documented NAT, S3 endpoint, state bootstrap, budget alert, alarm matrix, and
      guarded verified destroy are implemented.
- [x] The budget targets only the exact non-secret SNS topic ARN; one confirmed human SNS email
      destination is enrolled through a protected interactive human/SSO boundary after prerequisite
      apply and receives budget/drift alarms. No address enters Terraform, state, a saved plan, or a
      workflow artifact; alerts remain non-enforcing.
- [x] Initial deployment uses a reviewed prerequisites plan with runtimes disabled, verifies exact
      image/model/token prerequisites, then uses a second reviewed digest-pinned activation plan.
- [x] ECS deployment circuit breaker/rollback is enabled.
- [ ] Scheduled monitor task can read inputs and write reports.
- [x] SNS email enrollment is interactive, fail-closed before publication, and absent from Terraform
      state/plans and workflow artifacts. Budget and CloudWatch key-policy statements each enforce
      exact source-account, source-ARN, topic-context, and regional SNS ViaService conditions.
- [x] CloudWatch logs and alarms exist; every alarm has a tested native-service or bounded EMF source,
      and scheduler submission is not treated as monitor completion.
- [ ] `terraform destroy` removes the demo environment without orphaned resources.

## CI/CD

- [x] Pull-request workflows define lint, typecheck, tests, and security scans without AWS access.
- [x] Infrastructure plan is reviewable and not auto-applied from untrusted PRs.
- [x] Deployment workflow is manual and protected.
- [x] Each deployable Git-SHA image is built/scanned once and promoted by digest without rebuild;
      actions/base images are pinned.
- [ ] Post-deploy smoke test runs.
- [x] HTTPS smoke keeps the bearer token out of curl argv/environment and persisted evidence by
      validating it and supplying the Authorization header only through anonymous config stdin.
- [x] Failed deployment does not silently remain marked successful and has explicit protected ECS
      rollback with a separate model-pointer policy.

## Portfolio assets

- [ ] README contains architecture, quickstart, demo scenario, security, cost, and limitations.
- [ ] Architecture diagram is exported to PNG/SVG for LinkedIn/Upwork.
- [ ] 3–5 minute demo recording exists.
- [ ] At least four screenshots/GIFs exist.
- [ ] Case study explains the problem, trade-offs, implementation, evidence, and outcome.
- [ ] No active infrastructure or secrets remain after capture unless intentionally retained.
