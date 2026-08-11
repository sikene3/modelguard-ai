# Phase 10 Checklist

## Local code-only readiness segment

- [x] Starting branch/HEAD/clean-tree/no-remote boundary confirmed before editing
- [x] API SSM/S3 exact-VersionId bundle hydration, pre-deserialization verification, atomic install,
      and fail-closed readiness implemented
- [x] Dashboard typed regional endpoints, metric/log identities, and explicit degraded/unavailable
      source health implemented without mutating Phase 05 report states
- [x] Monitor one-shot `aws-run`, machine-readable output, deterministic evidence, idempotent report
      publication, bounded snapshots, and fail-closed exit categories implemented
- [x] Runtime verifier implementation inspects image contents/entrypoints, invalidates stale output,
      binds source/images/`uv.lock`, and activation rendering refuses absent or mismatched evidence
- [x] `team_protected` and honest `solo_portfolio` governance contracts documented and mutation-tested;
      automation is not represented as independent review
- [x] Retained manual `modelguard-ai-demo-monthly` USD 10 budget and exact four-alert contract defined;
      endpoint is Console-only and the read-only preflight never requests subscribers
- [x] Separate retained exact-state-object CloudTrail Terraform design and encrypted local-state
      preservation procedure added without init/plan/apply
- [x] Firehose `SubscriptionRequiredException` has a distinct read-only blocker and no fallback
- [x] Controlled future-Public checklist requires complete worktree/history/artifact/security audits
- [x] Locked operator environment includes exact Botocore-compatible `awscrt==0.36.0`; bootstrap
      verifies the import and version without starting AWS login or adding CRT to runtime images
- [x] Create-only model publisher verifies the local manifest/checksums and bounds, rejects all prior
      prefix version history, conditionally creates and reads back seven exact S3 VersionIds, and
      never deletes or activates a partial publication
- [x] Active/previous pointer promotion uses one conditional S3 lock, snapshot rechecks, previous-first
      ordering, exact SSM-version verification, compensating rollback, and retained-lock fail closure
      when rollback cannot be proven; the CLI has no secret-value or local-output arguments
- [x] Full local quality, security, coverage, Terraform-format, workflow, and repository scanner
      gates pass after the Ultra repairs
- [x] Historical pre-rewrite images from the repaired functional tree passed blocking Trivy
      HIGH/CRITICAL scans using Ubuntu Docker Engine, BuildKit, and Buildx; current clean-source
      immutable registry-digest evidence remains required before activation
- [x] The historical sealed three-image local-image-ID runtime verifier passed with AppArmor,
      built-in seccomp, and genuine `no-new-privileges`; its source/image/`uv.lock`-bound v2 record
      is not current publication provenance, and live activation remains fail-closed until matching
      clean-source registry-digest evidence exists
- [x] The historical pre-rewrite Compose smoke, healthy-to-drifted, browser-health,
      insufficient-data, corrupt-bundle, and sink-outage matrix passed using the repaired functional
      tree; it remains functional local evidence only, not current source-bound publication evidence.

## Live deployment segment — complete

- [x] Reviewed live-path corrections were merged through protected pull requests; clean-source
      model/image artifacts and their source-bound release evidence passed before activation
- [x] AWS identity confirmed with the browser-authenticated non-root operator profile in `us-east-1`
- [x] Account/Region/backend/tags/expiry/access-mode guardrails confirmed; ingress was exactly the
      verified runner address `41.68.210.73/32`, never world-open
- [x] Manual USD 10 budget exists and passes the value-free read-only preflight
- [x] Firehose account readiness passes without `SubscriptionRequiredException`
- [x] Retained CloudTrail design reviewed/applied; encrypted state, backup, and restore verified
- [x] Bootstrap trust boundary and the two least-privilege IAM reconciliation updates reviewed,
      applied, state-preserved, and read back with the temporary browser-authenticated identity
- [x] Public visibility, exact solo main ruleset, and the three contract environments reviewed and
      configured before Actions was enabled
- [x] GitHub variables and customized OIDC template configured only after matching AWS trust existed
- [x] Prerequisite saved plan applied with runtimes disabled
- [x] Each image scanned/pushed once and immutable digest resolved
- [x] Model `1.0.3` no-overwrite publish verified; exact manifest pointer promoted
- [x] `http_cidr_only` selected; no ACM/token value or token reference was used
- [x] Digest-pinned activation and exact `/32` ingress-update saved plans reviewed/applied
- [x] API and dashboard services stable; both ALB target groups healthy
- [x] Restricted-runner prediction reached the encrypted Firehose destination
- [x] One-shot monitor persisted an immutable report pair and EMF heartbeat, then returned the exact
      fail-closed insufficient-data category for the deliberately sub-threshold live sample
- [x] Provider-backed resource, IAM-boundary, encryption, logging, alarm, and cost inventory recorded
- [x] Exact image/model/task/schedule identities and ECS circuit-breaker rollback policy verified;
      the first-deployment explicit rollback correctly refused without an invented LKG record
- [x] Cleanup plan applied; initial and delayed service-specific inventories retained and verified
- [x] Raw plans remained encrypted/restricted; redacted evidence bound exact plan/source/account/backend
- [x] Live ECS/IAM hydration, dashboard source health, monitor `aws-run`, state restore, and teardown pass

## Evidence

- Commands: see `reports/phase-10.md`
- Test results: see `reports/phase-10.md`
- Artifact paths: complete raw evidence is mode-`0600` below the approved encrypted Phase 10 state
  root and checksum-mirrored below the encrypted backup root; only bounded identities are tracked
- Local-runtime baseline commit: `aad098ccb54d51c64a48b2105992d242f1c96b09`
- Blocker-remediation commit: `e5095af0114a938ffb7c779904e140f1db3c49a1`, exact message
  `fix: remediate Phase 10 live deployment blockers`
- Residual risks: `solo_portfolio` is not separation of duties; retained audit/bootstrap controls and
  the USD 10 Budget intentionally remain, while the disposable demo has zero live resource residuals
