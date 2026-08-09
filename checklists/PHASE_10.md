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
- [x] Production-equivalent images have been rebuilt from the final repaired worktree and their
      exact immutable IDs pass the blocking Trivy HIGH/CRITICAL scans using Ubuntu Docker Engine,
      BuildKit, and Buildx
- [x] The sealed three-image local-image-ID runtime verifier passes with AppArmor, built-in seccomp,
      and genuine `no-new-privileges`, and emits a source/image/`uv.lock`-bound v2 record; live
      activation remains fail-closed until future registry-digest evidence matches
- [x] The complete Compose smoke, healthy-to-drifted, browser-health, insufficient-data,
      corrupt-bundle, and sink-outage matrix passes using images rebuilt from the final repaired
      worktree. Historical pre-repair evidence was not promoted to current acceptance evidence.

## Live deployment segment — not authorized or executed

- [ ] AWS identity confirmed
- [ ] Account/Region/backend/tags/CIDR/budget/expiry/access-mode guardrails confirmed
- [ ] Manual USD 10 budget exists and passes value-free preflight
- [ ] Firehose account readiness passes without `SubscriptionRequiredException`
- [ ] Retained CloudTrail design reviewed/applied and its encrypted state preservation verified
- [ ] Bootstrap trust boundary reviewed with temporary browser-authenticated human identity
- [ ] GitHub governance mode, visibility, environments, protections, variables, OIDC template, and
      Actions-disabled setup reviewed and configured
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
  is sealed under the approved Phase 10 backup root and remediation evidence remains ignored locally;
  no live AWS evidence exists
- Local-runtime baseline commit: `MGH11___________________________________`
- Blocker-remediation commit identity: resolve the commit with exact message
  `fix: remediate Phase 10 live deployment blockers` from Git history; a report cannot embed its own
  content-addressed hash
- Residual risks: every unchecked live-deployment item above remains a blocker; the local code-only
  readiness segment is complete
