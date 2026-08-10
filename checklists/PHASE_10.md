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

## Live deployment segment — authorized; mutation not yet executed

- [ ] Commit the reviewed live-path guard corrections, regenerate the model bundle from that clean
      commit, and pass the clean-source release gate; the current dirty candidate passes all other
      applicable local gates and deliberately fails closed at the bundle provenance check
- [x] AWS identity confirmed with the browser-authenticated non-root operator profile in `us-east-1`
- [ ] Account/Region/backend/tags/CIDR/budget/expiry/access-mode guardrails confirmed
- [x] Manual USD 10 budget exists and passes the value-free read-only preflight
- [x] Firehose account readiness passes without `SubscriptionRequiredException`
- [ ] Retained CloudTrail design reviewed/applied and its encrypted state preservation verified
- [ ] Bootstrap trust boundary reviewed with temporary browser-authenticated human identity
- [x] Public visibility, exact solo main ruleset, and the three contract environments reviewed and
      configured while Actions remains disabled
- [ ] GitHub variables and OIDC template configured only after the matching AWS trust exists
- [ ] Prerequisite saved plan applied with runtimes disabled
- [ ] Each image scanned/pushed once and immutable digest resolved
- [ ] Model no-overwrite publish verified; exact manifest pointer promoted
- [ ] Token ARN/ACM verified for HTTPS-token mode; no token value captured
- [ ] Second saved digest-pinned activation plan reviewed/applied
- [ ] Targets healthy
- [ ] Firehose delivery verified
- [ ] Monitor/report verified
- [ ] Resource inventory recorded
- [ ] Exact image/model identity and rollback targets verified
- [ ] Cleanup plan and post-destroy verification prepared
- [ ] Raw plans restricted/redacted; exact plan/commit/account/backend identities match
- [ ] Live ECS/IAM runtime hydration, dashboard source health, monitor `aws-run`, and teardown pass

## Evidence

- Commands: see `reports/phase-10.md`
- Test results: see `reports/phase-10.md`
- Artifact paths: local-only evidence is listed in `reports/phase-10.md`; baseline private evidence
  is sealed under the approved Phase 10 backup root; account-level read-only AWS prerequisite evidence
  exists, but no live deployment/runtime evidence exists
- Local-runtime baseline commit: `aad098ccb54d51c64a48b2105992d242f1c96b09`
- Blocker-remediation commit: `e5095af0114a938ffb7c779904e140f1db3c49a1`, exact message
  `fix: remediate Phase 10 live deployment blockers`
- Residual risks: every unchecked live-deployment item above remains a blocker; the local code-only
  readiness segment and account-level read-only prerequisites are complete
