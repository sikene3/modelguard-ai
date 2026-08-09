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
- [x] AWS API startup hydrates every exact pointer VersionId into an isolated bounded staging
      directory, verifies all immutable and cross-artifact contracts before deserialization,
      proves the exact bucket Region, rejects duplicate-key SSM JSON and unproven existing bytes,
      installs atomically under measured task-safe size bounds, and remains not-ready after
      corruption, substitution, or interruption.

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
- [x] `aws-run` executes exactly one bounded AWS monitoring cycle, emits one machine-readable v1
      result, persists conditional evidence, preserves local `run`/`status`, and returns documented
      fail-closed codes for configuration, permission, evidence, Region, and sink failures.
- [x] AWS prediction enumeration accepts only Terraform's exact Firehose `.jsonl.gz` suffix, binds
      prefix and `MaxKeys`, bounds pages and every returned entry, rejects token cycles and malformed
      pages, and requires the canonical semantic monitoring-policy SHA-256 before AWS access.

## Dashboard

- [x] Shows separate run/data-quality/drift/performance status and timestamp.
- [x] Shows active model identity separately from report target identity and accepted target volume.
- [x] Shows top drifting features and distributions.
- [x] Handles missing/stale reports honestly.
- [x] Loads from local storage and S3 through the same repository interface.
- [x] AWS dashboard configuration binds exact Region, S3/CloudWatch/Logs endpoints, metric/log
      identities, and dashboard identity; missing, denied, wrong-Region, malformed, and partial
      sources render explicit degraded/unavailable health without mutating report states. Health
      and report reads use the same exact validated S3 endpoint, and the completion metric is
      consistently `MonitorCompletions` from EMF through Terraform and the dashboard.

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
- [x] Two AZs, one documented NAT, S3 endpoint, state bootstrap, alarm matrix, and guarded verified
      destroy design are implemented.
- [x] The retained manual budget contract is exactly `modelguard-ai-demo-monthly`, USD 10 monthly,
      with 50/80/100 percent actual and 100 percent forecast alerts. Its read-only preflight never
      retrieves subscriber endpoints; no address enters project files, Terraform, state, saved
      plans, workflows, artifacts, reports, logs, commands, or examples; alerts are non-enforcing.
- [ ] The retained manual USD 10 budget and its Console-entered notification endpoint exist in the
      target AWS account and pass the value-free read-only preflight.
- [x] A separate retained CloudTrail Terraform design limits S3 data events to the exact future
      state and lock objects, uses protected encrypted storage with finite retention and
      `prevent_destroy`, and documents encrypted local-state preservation and usage costs.
- [ ] The retained CloudTrail prerequisite has been separately reviewed, applied, state-preserved,
      and verified in AWS.
- [x] Initial deployment uses a reviewed prerequisites plan with runtimes disabled, verifies exact
      image/model/token prerequisites, then uses a second reviewed digest-pinned activation plan.
- [x] ECS deployment circuit breaker/rollback is enabled.
- [ ] Scheduled monitor task can read inputs and write reports.
- [x] The local production-equivalent runtime verifier checks actual API hydration, typed dashboard
      AWS health, and one-shot monitor contents/entrypoints; activation evidence must match all three
      immutable image references before `runtime_contract_verified` can be true in rendered inputs.
- [x] A sealed three-image verifier run has passed all required host controls and produced a record
      bound to the exact immutable local image IDs, source revision, and `uv.lock`. AppArmor,
      built-in seccomp, and genuine `no-new-privileges` passed. The Terraform default remains false
      until a future authorized activation supplies matching immutable registry-digest evidence.
- [x] Drift/alarm SNS email enrollment is interactive, fail-closed before publication, and absent
      from Terraform state/plans and workflow artifacts. Retained Budget and CloudWatch key-policy
      statements remain independently restricted by exact source-account, source-ARN, topic-context,
      and regional SNS ViaService conditions; the manual budget itself is not Terraform-owned.
- [x] CloudWatch logs and alarms exist; every alarm has a tested native-service or bounded EMF source,
      and scheduler submission is not treated as monitor completion.
- [ ] `terraform destroy` removes the demo environment without orphaned resources.

## CI/CD

- [x] Pull-request workflows define lint, typecheck, tests, and security scans without AWS access.
- [x] Infrastructure plan is reviewable and not auto-applied from untrusted PRs.
- [x] Deployment workflow is manual and protected.
- [x] `team_protected` and `solo_portfolio` governance contracts are distinct and fail closed;
      solo mode truthfully lacks independent review, requires Public visibility before Actions,
      preserves exact OIDC/role separation, and has a documented upgrade path to team protection.
- [x] Solo plan/apply and destroy are real separate protected manual boundaries that bind exact
      run/source/plan/identity/image/model evidence and typed phrases. Raw plans and image metadata
      use confidential transfers or private storage, never Public artifacts; deployed state and the
      last-known-good record prevent governance-mode downgrade by omission or variable change.
- [x] Human apply, destroy, enrollment, and readiness helpers require the exact
      `modelguard-bootstrap` browser-login profile and reject root, static keys, environment
      credentials, and workflow callers; workflow checks separately require the exact OIDC role.
- [ ] The repository has passed the future-publication audit, been deliberately made Public with
      Actions disabled, and had the selected governance mode configured in GitHub.
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
