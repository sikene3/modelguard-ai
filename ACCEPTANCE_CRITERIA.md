# ModelGuard AI — Acceptance Criteria

## Global release gate

The MVP is portfolio-ready only when every required criterion below is evidenced by a command output, test, screenshot, report, or demo recording.

## Data and training

- [x] Dataset generation is deterministic for a fixed seed.
- [x] Schema and data-quality checks fail clearly on malformed data.
- [x] Training uses a single sklearn Pipeline including preprocessing.
- [x] Split is persisted before fitting; calibration is train-only; threshold is validation-only;
      the held-out test is evaluated once per training invocation after threshold lock.
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
- [x] GitHub Actions uses customized exact-subject OIDC, not stored AWS access keys; IAM was updated
      before the matching repository subject template, and live plan/deploy claim exchange passed
      with the exact bounded roles.
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
- [x] The operator-only locked environment pins and imports `awscrt==0.36.0`, exactly satisfying
      locked Botocore's browser-login extra without adding CRT to any runtime-image dependency group;
      bootstrap verifies this dependency locally before any interactive login.
- [x] The retained manual USD 10 budget exists in the target account and its four-notification
      contract passes the value-free read-only preflight; the Console-entered subscriber endpoint is
      operator-attested and deliberately neither queried nor recorded.
- [x] A separate retained CloudTrail Terraform design limits S3 data events to the exact future
      state and lock objects, uses protected encrypted storage with finite retention and
      `prevent_destroy`, and documents encrypted local-state preservation and usage costs.
- [x] The retained CloudTrail prerequisite has been separately reviewed, applied, state-preserved,
      and verified in AWS.
- [x] The guarded deployment design requires a reviewed prerequisites plan with runtimes disabled,
      exact image/model/access prerequisite verification, and a second reviewed digest-pinned
      activation plan; the live applies and exact `/32` ingress update were evidence-bound.
- [x] The model publisher verifies the strict seven-file bundle and measured size bounds before AWS,
      refuses any current or historical object under the semantic-version prefix, uses conditional
      create-only writes plus exact checksum/VersionId readback, publishes the checksum index last,
      and changes no pointer until all seven objects pass.
- [x] Active/previous promotion is serialized by an owner-verified conditional S3 lock, rechecks both
      SSM snapshots, writes previous before active, verifies each new parameter version, restores both
      snapshot values after any attempted failure, and retains the lock if rollback cannot be proven.
      The CLI accepts no credential/secret-value or local-output argument and emits bounded identity
      metadata only.
- [x] ECS deployment circuit breaker/rollback is enabled.
- [x] Scheduled monitor task read the active model/prediction inputs, wrote an immutable report pair
      plus EMF heartbeat, and failed closed with the exact insufficient-data category below 500 rows.
- [x] The local production-equivalent runtime verifier checks actual API hydration, typed dashboard
      AWS health, and one-shot monitor contents/entrypoints; activation evidence must match all three
      immutable image references before `runtime_contract_verified` can be true in rendered inputs.
- [x] A pre-rewrite sealed three-image verifier run passed AppArmor, built-in seccomp, genuine
      `no-new-privileges`, and all other required host controls. It remains historical functional
      evidence only; activation used the newly generated clean-source immutable registry-digest
      record and enabled the runtime contract only after all three image identities matched.
- [x] Drift/alarm SNS email enrollment is interactive, fail-closed before publication, and absent
      from Terraform state/plans and workflow artifacts. Retained Budget and CloudWatch key-policy
      statements remain independently restricted by exact source-account, source-ARN, topic-context,
      and regional SNS ViaService conditions; the manual budget itself is not Terraform-owned.
- [x] The Terraform design defines CloudWatch logs and alarms; every alarm has a tested
      native-service or bounded EMF source, and scheduler submission is not treated as monitor
      completion. All 12 live alarm/source contracts were inventoried before teardown.
- [x] The exact saved `terraform destroy` plan removed the disposable demo environment. Terraform
      state was verified empty and every explicitly inventoried demo service namespace was empty;
      only validated nonbillable provider/tag metadata and the required retained Budget remained.

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
- [x] The sanitized baseline passed the checksum-verified Publication Audit, was deliberately made
      Public with Actions disabled, and received the exact solo `main` ruleset plus the three
      contract environments.
- [x] Repository variables, customized OIDC claims, and matching AWS trust are configured and read
      back before Actions is enabled.
- [x] Each deployable Git-SHA image is built/scanned once and promoted by digest without rebuild;
      actions/base images are pinned.
- [x] The replacement restricted runner passed live/ready/version/prediction and dashboard health
      from the exact reviewed runner `/32` ingress rule; the raw address is excluded from the
      current publication tree.
- [x] HTTPS smoke keeps the bearer token out of curl argv/environment and persisted evidence by
      validating it and supplying the Authorization header only through anonymous config stdin.
- [x] Failed deployment does not silently remain marked successful and has explicit protected ECS
      rollback with a separate model-pointer policy.

## Portfolio assets

- [x] README contains architecture, quickstart, demo scenario, security, cost, and limitations.
- [x] Architecture diagram is exported to PNG/SVG for LinkedIn/Upwork.
- [x] 3–5 minute demo recording exists.
- [x] At least four screenshots/GIFs exist.
- [x] Case study explains the problem, trade-offs, implementation, evidence, and outcome.
- [x] No disposable demo infrastructure or secrets remain after capture; the USD 10 Budget and
      retained audit/bootstrap control plane remain intentionally.

The genuine current-run recording is 255.036 seconds at 1280×720, and the 15-second animated GIF is
derived from its healthy-to-degraded interval. Both passed the Phase 13 privacy and media checks;
the existing four reviewed dashboard PNGs remain unchanged.
