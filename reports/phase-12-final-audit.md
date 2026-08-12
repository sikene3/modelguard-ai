# Phase 12 — Ultra final audit

## Release verdict

**PASS — the final Ultra audit is complete. H12-01 through H12-06 are closed, zero Critical or High
findings remain, and every Medium/Low finding has a recorded final disposition.**

The four independent workstreams found no Critical issue and reproduced six High-severity defects
that crossed core monitoring and AWS security boundaries. Repair Batch A closed H12-01 and H12-02;
Repair Batch B closed H12-03 through H12-06. The single canonical `make release-gates` invocation
authorized for Batch A stopped only because the exact suppression-registry test still expected the
pre-boundary count. The count was corrected, its focused test passed, and each not-yet-run or
affected gate passed without restarting the canonical target. Batch B preserved that exact-once
evidence and used focused tests plus permitted non-canonical quality gates.

The repair base was `a15f3b2ed02796a914d1d3e0f56a0b1475e596b4` on `main`, equal to
`origin/main` before this report was written. The audit and both repair batches made no AWS or
GitHub call and did not run Terraform apply/destroy. All observations are local, read-only, or
derived from already tracked reports and private-evidence hashes.

## Scope and methodology

The audit followed four independent workstreams:

1. application correctness and Python quality;
2. ML/statistical validity and public-claim accuracy;
3. AWS, Terraform, IAM, security, and teardown safety; and
4. CI/CD, containers, tests, documentation, portfolio, and reproducibility.

Each workstream inspected source, tests, workflows, Dockerfiles, Terraform, reports, documentation,
portfolio assets, and relevant Git history. Focused probes exercised production code paths without
network or cloud mutation. Findings are ranked by plausible impact, with compensating controls
explicitly considered.

Severity totals:

| Severity | Initial count | Final disposition | Release effect |
| --- | ---: | ---: | --- |
| Critical | 0 | 0 | None found |
| High | 6 | 6 fixed; 0 open | No release-blocking finding remains |
| Medium | 8 | 8 accepted risks | Bounded MVP limitations with compensating controls |
| Low | 9 | 3 fixed; 6 accepted risks | No release blocker |

## Repair Batch A evidence

- **H12-01 resolved:** every dispatch value used by a workflow shell is mapped through `env` and
  referenced as a quoted shell variable. A parsed-workflow regression rejects `${{ inputs.* }}` and
  `${{ github.event.inputs.* }}` in every `run` body. An adversarial `$()` value remains literal and
  does not execute.
- **H12-02 resolved:** the deploy role no longer has `ManageGuardedDemoNetwork` or an EC2 lifecycle
  `Resource = "*"` allow. Creation, creation-time tagging, parent-resource use, mutation,
  association, and deletion are separate statements over exact account/Region ARN types. Creation
  requires the ModelGuard request-tag contract; lifecycle operations require the ModelGuard
  resource-tag contract. A role permissions boundary explicitly denies wrong-Region EC2 calls and
  foreign project/environment lifecycle calls.
- Focused verification: 198 Phase 08/09 Terraform, IAM, workflow, and governance tests passed;
  bootstrap Terraform validation and recursive formatting passed. The one canonical release-gate
  invocation ran Ruff, strict Mypy, and all 604 tests at 83.56% coverage; 603 passed and the sole
  failure was the stale exact Checkov-suppression count (`61` versus the six reviewed
  boundary-only false-positive annotations). After updating that invariant to `67`, its focused
  test passed. Bandit, strict hashed pip-audit, the basic secret gate, actionlint, ShellCheck,
  Gitleaks, Trivy, model verification, and portfolio checks passed; the affected bootstrap Checkov
  rerun passed 200 checks with zero failures. The full target was deliberately not restarted.
- No GitHub, AWS, Terraform apply/destroy, commit, push, publication, or history-rewrite operation
  occurred. Existing Phase 12 evidence was retained.
- **Readiness after Batch A:** H12-01 and H12-02 were closed; H12-03 through H12-06 proceeded under
  the separately authorized Batch B boundary.

## Repair Batch B evidence

- **H12-03 resolved:** invalid deflate data is normalized only at the two GZIP boundaries, and the
  shared strict JSON parser imposes an iterative 100-level nesting bound and normalizes parser
  recursion failures. Local CLI, real AWS CLI, and dashboard regressions prove bounded failure;
  the AWS path returns exit 4, emits exactly one JSON result, and persists a failed run status.
- **H12-04 resolved:** one strict external-artifact loader now preserves duplicate-key,
  non-finite-value, and nesting rejection, canonicalizes JSON, and validates Pydantic models with
  `strict=True`. Dashboard, report/status/manifest, prediction-event, delayed-label, active-pointer,
  publisher, local evidence, and Phase 11 readers use it. Coercive numeric-string, boolean-string,
  and float-to-integer cases are rejected while valid JSON datetime/UUID values remain accepted.
- **H12-05 resolved:** AWS snapshots enumerate only the finite UTC hour partitions overlapping the
  monitoring window and finalization allowance. Page, entry, object, compressed-byte, and
  decoded-byte limits are shared globally across prefixes, and duplicate keys are counted once.
  Rollover, overlap, deduplication, exhaustion, corrupt-GZIP, and actual AWS-cycle regressions pass.
- **H12-06 resolved:** the baseline contract is now `modelguard.baseline-profile.v2` with explicit
  ordered false/true counts and proportions for `is_new_device`; monitoring uses categorical JS
  distance instead of the blind numeric PSI bucket. The regenerated local verification bundle has
  manifest SHA-256 `0e2c9ce28f3307d57a72a2e459e53646ecdcb44566c39a2cde6340936ec673c8`
  and baseline SHA-256 `7166ff1aa880e58d6d96e1fe911b45c3d7d34bca8612fb02b96c43ed6ce1ec9d`.
  It is an uncommitted-repair verification artifact, not clean-source release provenance. The
  previous v1 bundle remains recoverable in the ignored repair staging area.
- Production-path boolean evidence: a baseline-like population remained `healthy` at
  `0.000000000000`; all-false and all-true populations became `degraded` at `0.315518379703` and
  `0.793181609847`. Historical immutable Phase 11 evidence was not rewritten; its superseded signal
  is qualified and future reruns require `categorical_js_distance` for `is_new_device`.
- Focused verification: H12-03 `4 passed`; H12-04 `27 passed` (`27 deselected`); H12-05 `6 passed`;
  H12-06 `2 passed`; the directly affected application/monitoring selection `166 passed`; and the
  Phase 11/schema/runtime selection `41 passed`. Strict Mypy passed all 77 source files after the
  shared loader was generalized to external `BaseModel` contracts.
- No canonical `make release-gates`, GitHub, AWS, Terraform apply/destroy, commit, push,
  publication, or history-rewrite operation occurred in Batch B.
- Final permitted non-canonical verification: `make test` passed 618 tests at 83.70% coverage;
  Bandit, strict hash-verified pip-audit, basic secret defense, actionlint, ShellCheck, Checkov
  (Terraform 524, Dockerfile 317, GitHub Actions 956; zero failures), policy-reviewed Gitleaks, and
  Trivy passed. Current model verification and portfolio validation passed. Ruff initially reported
  one deterministic formatting difference in the new boolean-drift branch; Ruff formatted that one
  file, the affected H12-06 regression passed, and the complete lint gate then passed.
- **Readiness:** zero initial High findings remain open. The repository is ready for the final
  Ultra audit; the eight Medium and nine Low findings remain explicit inputs to that audit and are
  not represented as repaired.

## Final Ultra audit verdict

The final audit re-read the complete Phase 12 diff, governing specification, architecture,
acceptance criteria, phase prompt, checklist, source, tests, workflows, IAM, public claims, and
reconciled evidence. H12-01 through H12-06 remain closed under their focused regression evidence.
No new Critical or High issue was found. The accepted risks below do not claim production-grade
coverage: they are bounded by the explicitly local/synthetic/temporary MVP, compensating controls,
and corrected public wording.

| ID | Disposition | Concrete evidence and boundary |
| --- | --- | --- |
| M12-01 | **ACCEPTED_RISK** | Strict v1 events reject missing/null required features before acceptance and the rejected-fraction voter warns/invalidates data quality. `docs/MONITORING_CONTRACT.md` and CL-13 now state that accepted-event missingness does not attribute rejected raw fields. |
| M12-02 | **ACCEPTED_RISK** | Delayed labels are local, optional, synthetic, and explicitly outside AWS/online collection. Timestamp syntax is strict, but logical label eligibility remains the trusted source's responsibility and is now disclosed; performance claims remain limited to the supplied labeled subset. |
| M12-03 | **ACCEPTED_RISK** | The local run-status adapter is now documented as a single-writer demo boundary. Local report `latest` is locked and immutable history is create-only; the deployed S3 adapter uses conditional writes and is process-safe. |
| M12-04 | **ACCEPTED_RISK** | `report_id` is now explicitly documented as semantic-input identity, not content authentication. History is immutable/create-only, generated evidence records JSON SHA-256, and AWS evidence additionally binds object identity; no claim treats `report_id` alone as a byte digest. |
| M12-05 | **ACCEPTED_RISK** | The ignored baseline-v2 bundle passes complete internal verification and smoke, but its dirty-source lineage is not represented as release provenance. The report and checklist require a newly regenerated clean-source bundle before any future publish/deploy. No deployment is active. |
| M12-06 | **ACCEPTED_RISK** | The historical Phase 10 destroy has externally retained state-zero and service-inventory evidence, and the human recovery runbook includes `state pull | verify-empty-managed-state`. The ordinary workflow's missing immediate state-zero call remains a documented future hardening item; exact delete-only plan apply plus two authoritative service inventories protect the billable-resource boundary. |
| M12-07 | **ACCEPTED_RISK** | The Phase 10 evidence README now explicitly supersedes its earlier local-only section and records source/plan/artifact hashes and bounded counts. Raw state/inventory receipts and their complete checksum chain remain encrypted/private by design rather than copied into the Public repository. |
| M12-08 | **ACCEPTED_RISK** | CI's inline Mypy list omits three scripts, but the canonical local `make typecheck` includes them and passed all 77 source files in this repair. CI/list unification remains future hardening; no current type failure is hidden. |
| L12-01 | **ACCEPTED_RISK** | The committed repeated-stationary test reuses a seed, but the audit's distinct-seed production probe evaluated 60 independent windows and all remained healthy (maximum score PSI `0.0751`, below warning). |
| L12-02 | **ACCEPTED_RISK** | Teardown has no dedicated ENI/NACL query. Empty authoritative VPC, subnet, NAT, ALB/ECS, route, security-group, tagging, and service inventories plus zero managed state bound the historical disposable/billable claim; the broader future-inventory wording remains narrowed to the implemented verifier. |
| L12-03 | **FIXED** | Notification documentation now states the real boundary: the verifier transiently reads the sole endpoint in memory but accepts no address input and emits/persists only a value-free subscriber count. |
| L12-04 | **ACCEPTED_RISK** | The CI Terraform job omits retained `audit-bootstrap`, while locked local Phase 10/12 evidence validates all three roots. The retained root is outside disposable demo planning; adding it to CI remains bounded hardening. |
| L12-05 | **ACCEPTED_RISK** | Yamllint's top-level version is exact but its transitive tool environment is not repository-locked. It is a compatibility lint only; checksum-locked actionlint/ShellCheck independently enforce workflow and embedded-shell policy. |
| L12-06 | **ACCEPTED_RISK** | Manifest parity is not yet a canonical CI target. This final audit independently proves sorted, unique, exact parity for all candidate paths and checks it again after the final commit. |
| L12-07 | **ACCEPTED_RISK** | Portfolio validation can expose a local absolute path only on failure. Successful evidence is bounded, final privacy/security scans contain no such path, and the validator has no credential/cloud boundary. |
| L12-08 | **FIXED** | Specification, acceptance criteria, README, case study, ADR, prompt, checklist, generated model-card wording, and CL-05 now say once per training invocation after threshold lock; no repository-lifetime single-evaluation claim remains. |
| L12-09 | **FIXED** | The raw runner `/32` was removed from the current report, checklist, and acceptance tree and replaced with “exact reviewed runner `/32`.” Its already-published historical occurrence is acknowledged without rewriting published history. |

Final disposition totals are therefore zero open Critical/High findings, eight accepted Medium
risks, three fixed Low findings, and six accepted Low risks. None is `NOT_APPLICABLE`; each was
evaluated against the actual MVP boundary rather than dismissed.

Final-audit focused verification passed: four training-workflow tests; targeted strict Mypy and
Ruff; portfolio validation across 30 claims, 188 links, four screenshots, and both media assets;
the basic secret/file gate; a redacted current-candidate Gitleaks scan with zero findings; removal of
the historical raw runner CIDR and private repository path from all 348 candidate files; exact
sorted/unique manifest and JSON status parity; and `git diff --check`. These checks are incremental
to the preserved Batch A/B evidence and are not presented as a canonical `release-gates` rerun.

## High findings

### H12-01 — Workflow-dispatch input can become shell commands under the deploy role — resolved

**References:** `.github/workflows/destroy-demo.yml:111-138`,
`.github/workflows/destroy-demo.yml:157-178`, and `tests/unit/test_phase09_cicd.py:2679-2700`.

The protected destroy job assumes the AWS deploy role and then inserts
`${{ inputs.auto_destroy_date }}` directly into multiline Bash `run` blocks. GitHub evaluates the
expression before Bash parses the script; surrounding the expression with double quotes does not
disable `$()` or backtick command substitution. The current unit test positively requires this
unsafe text form instead of rejecting expressions in shell bodies.

Reproduction:

```bash
rg -n -- '--auto-destroy-date "\$\{\{ inputs\.auto_destroy_date \}\}"' \
  .github/workflows/destroy-demo.yml tests/unit/test_phase09_cicd.py
bash -c 'candidate="$(printf harmless_expansion)"; printf "%s\n" "$candidate"'
```

Result: two credentialed workflow locations and the approving test were found; the harmless probe
demonstrated that command substitution executes inside a double-quoted value.

**Smallest correct remediation — XHigh:** map every dispatch input to a step-level environment
variable and reference only the quoted environment variable from Bash. Apply the same rule to
`source_commit` and every other input used in `run`. Validate syntax before role assumption where
possible. Replace the string-presence test with parsed-workflow policy coverage that rejects
`${{ inputs.* }}` in all `run` values and includes an adversarial harmless `$()` fixture.

### H12-02 — The deploy role can mutate unrelated EC2 networking resources — resolved

**References:** `infrastructure/bootstrap/iam.tf:704-748`,
`infrastructure/bootstrap/iam.tf:1134-1144`, `infrastructure/bootstrap/iam.tf:1173-1189`, and
`tests/unit/test_phase08_terraform.py:2010-2038`.

`ManageGuardedDemoNetwork` grants create, modify, detach, release, and delete operations—including
`ec2:DeleteVpc`—against `Resource = "*"`. The statement has no `aws:RequestedRegion`, request-tag,
resource-tag, or resource-ARN condition. Saved plans, tags, CLI Region selection, and repository
guards are procedural controls; they are not an IAM authorization boundary and cannot constrain an
arbitrary AWS CLI call made with the role. This materially amplifies H12-01.

Reproduction:

```bash
sed -n '704,748p' infrastructure/bootstrap/iam.tf
rg -n 'aws:RequestedRegion|aws:ResourceTag|aws:RequestTag' infrastructure/bootstrap/iam.tf
```

Result: the wildcard network statement contains the destructive actions and none of the returned
tag conditions belongs to it.

**Smallest correct remediation — Max:** split create, tag, mutation, association, and delete actions
according to the EC2 service-authorization model. Require the exact Region on every regional
statement, supported request tags on creation, `ec2:CreateAction` for creation-time tagging, and
exact resource tags/ARN patterns on addressable mutations. Isolate only genuinely
non-resource-addressable actions. Add a permissions boundary or session policy as defense in depth,
then semantically test denial for a foreign-tagged VPC and a second Region.

### H12-03 — Corrupt monitoring evidence can escape the canonical failure result — resolved

**References:** `src/modelguard/monitoring/aws.py:217-222`,
`src/modelguard/monitoring/events.py:186-201`, `src/modelguard/monitoring/events.py:249-253`,
`src/modelguard/monitoring/aws_run.py:346-380`, `src/modelguard/monitoring/cli.py:126-138`, and
`src/modelguard/dashboard/parsing.py:152-155`.

The GZIP readers normalize `gzip.BadGzipFile` and `EOFError`, but invalid deflate bytes can raise
`zlib.error`. Deeply nested JSON can raise `RecursionError`. Neither class is normalized by the
shared parser or the documented local/AWS/dashboard boundaries. One corrupt Firehose object can
therefore terminate `aws-run` before its one canonical JSON result and before normal failure-status
persistence; the dashboard can also crash instead of rendering malformed/unavailable evidence.

Reproduction:

```bash
uv run --frozen --no-sync python - <<'PY'
from io import BytesIO
from modelguard.monitoring.aws import freeze_s3_raw_snapshot

payload = b'\x1f\x8b\x08\x00' + b'x' * 30
class S3:
    def list_objects_v2(self, **_):
        return {'Contents': [{'Key': 'predictions/year=2026/month=08/day=12/hour=10/bad.jsonl.gz'}],
                'IsTruncated': False}
    def head_object(self, **_):
        return {'ETag': '"e"', 'VersionId': 'v1', 'ContentLength': len(payload)}
    def get_object(self, **_):
        return {'Body': BytesIO(payload), 'ETag': '"e"', 'VersionId': 'v1'}
try:
    freeze_s3_raw_snapshot(S3(), bucket='events', prefix='predictions/')
except Exception as error:
    print(type(error).__name__, isinstance(error, ValueError))
PY
```

Result: `error False`, not the bounded `ValueError` path. A 1,200-level JSON array similarly raised
an unnormalized `RecursionError`.

**Smallest correct remediation — XHigh:** normalize `zlib.error` at both GZIP boundaries and
`RecursionError` in the shared strict JSON parser to bounded domain errors; do not broad-catch all
exceptions. Add full-boundary local CLI, `aws-run`, and dashboard regressions. The AWS regression
must prove exit code 4, exactly one bounded JSON result, and persisted failed-run state.

**Batch B result:** implemented exactly at the shared parser and two GZIP boundaries. The bounded
local CLI, actual AWS CLI, persisted-status, and dashboard regressions pass; no broad exception
catch was added.

### H12-04 — Runtime artifact parsing is coercive while the checked-in schema is strict — resolved

**References:** `src/modelguard/core/serialization.py:15-18`,
`src/modelguard/core/serialization.py:100-105`, `src/modelguard/dashboard/parsing.py:74-94`, and
`contracts/monitoring-report-v1.schema.json:941-944`.

The common artifact model forbids extra/non-finite values but does not enable strict validation.
External artifact readers validate parsed Python objects in Pydantic's coercive mode. A monitoring
report with `records.counts.raw` encoded as a JSON string is rejected by the exported JSON Schema,
yet accepted and silently converted to an integer by the dashboard reader. The same shared boundary
serves reports, run status, bundle/config, and lineage models.

Reproduction:

```bash
uv run --frozen --no-sync python - <<'PY'
import json
from pathlib import Path
from jsonschema import Draft202012Validator
from modelguard.dashboard.parsing import parse_monitoring_report
from modelguard.dashboard.repository import RawArtifact

p = Path('artifacts/phase-11-evidence/phase11-final-local-04/monitoring/transition-reports/latest.json')
value = json.loads(p.read_bytes())
value['records']['counts']['raw'] = str(value['records']['counts']['raw'])
schema = json.loads(Path('contracts/monitoring-report-v1.schema.json').read_bytes())
print(bool(list(Draft202012Validator(schema).iter_errors(value))))
print(type(parse_monitoring_report(RawArtifact(json.dumps(value).encode(), None)).records.counts.raw).__name__)
PY
```

Result: the schema reported an error while the runtime returned `int`.

**Smallest correct remediation — XHigh:** preserve duplicate-key/non-finite rejection, then use one
shared `model_validate_json(..., strict=True)` external-artifact loader. Route direct dashboard,
status, manifest, monitoring-config, and bundle readers through it. Add schema/runtime parity tests
for numeric strings, boolean strings, float-to-integer coercion, and valid JSON datetime/UUID values.

**Batch B result:** implemented through the shared strict external-model loader and routed through
all audited external artifact boundaries. Schema/runtime coercion regressions and valid typed JSON
regressions pass.

### H12-05 — AWS monitoring scans the lifetime prediction prefix — resolved

**References:** `src/modelguard/monitoring/aws_run.py:256-263`,
`src/modelguard/monitoring/aws.py:99-229`, `src/modelguard/inference/events.py:45-48`, and
`docs/adr/ADR-003-firehose-to-s3.md:15-18`.

The monitor resolves a recent finalized window but always enumerates `predictions/`. Object, page,
entry, compressed-byte, and decoded-byte bounds therefore apply to all historical events before
payload event-time filtering. Old traffic grows monotonically until it can make every current run
fail the bounded snapshot, even when the requested hour is small and valid. Existing tests assert
the lifetime prefix and therefore reinforce the mismatch with the ADR.

Reproduction:

```bash
uv run --frozen --no-sync python - <<'PY'
from modelguard.monitoring.aws import _enumerate_s3_objects
class S3:
    def list_objects_v2(self, **kwargs):
        start = int(kwargs.get('ContinuationToken', '0'))
        stop = min(start + 1000, 10001)
        result = {
            'Contents': [
                {'Key': f'predictions/year=2020/month=01/day=01/hour=00/{i:05d}.jsonl.gz'}
                for i in range(start, stop)
            ],
            'IsTruncated': stop < 10001,
        }
        if stop < 10001:
            result['NextContinuationToken'] = str(stop)
        return result
try:
    _enumerate_s3_objects(S3(), bucket='events', prefix='predictions/', maximum_objects=10000)
except ValueError as error:
    print(error)
PY
```

Result: historical objects alone caused `S3 prediction snapshot exceeds the object-count limit`.

**Smallest correct remediation — XHigh:** derive the finite physical UTC hour prefixes overlapping
the event window and documented arrival/finalization allowance. Enumerate only those prefixes while
sharing one global page/entry/object/compressed/decoded-byte budget, deduplicate object identity,
and retain authoritative payload event-time filtering. Test midnight, month/year rollover,
overlap, duplicate objects, and global-budget exhaustion.

**Batch B result:** implemented with finite UTC hour prefixes, authoritative payload event-time
filtering, global shared budgets, and global key deduplication. Rollover, overlap, duplicate, and
every bounded-exhaustion regression passes.

### H12-06 — The boolean feature's own drift signal is mathematically blind — resolved

**References:** `src/modelguard/data/schema.py:26-34`,
`src/modelguard/training/baseline.py:147-207`, `src/modelguard/monitoring/drift.py:194-222`, and
`portfolio/claims-ledger.md:25`.

`is_new_device` is treated as numeric. Its boolean training domain collapses to edges `[0.0, 1.0]`
and one inclusive interval containing both values. The production PSI path therefore maps an
all-false population, the baseline mixture, and an all-true population to the same counts and
reports `0.0/healthy` for each.

Reproduction through the current verified baseline and production `_numeric_counts` plus
`evaluate_distribution_signal` path:

```bash
uv run --frozen --no-sync python - <<'PY'
from pathlib import Path
from modelguard.monitoring.config import MonitoringConfig
from modelguard.monitoring.drift import _numeric_counts, evaluate_distribution_signal
from modelguard.training.bundle import inspect_bundle

metadata = inspect_bundle(Path('artifacts/model-bundles/1.0.0'))
profile = metadata.baseline.numeric_features['is_new_device']
config = MonitoringConfig.model_validate_json(
    Path('configs/phase-05-monitoring.json').read_text()
)
baseline = [float(item.proportion.value or 0.0) for item in profile.bins]
for name, values in (
    ('all_false', [False] * 500),
    ('baseline_mix', [False, True] * 250),
    ('all_true', [True] * 500),
):
    counts = _numeric_counts(values, profile)
    signal = evaluate_distribution_signal(
        name='is_new_device', kind='numeric_psi', baseline=baseline,
        current_counts=counts or [], universe=[item.semantic for item in profile.bins],
        config=config, constant=profile.constant,
    )
    print(name, counts, signal.value, signal.state.value)
PY
```

Observed:

```text
all_false    [0, 500, 0]  PSI=0.0  healthy
baseline_mix [0, 500, 0]  PSI=0.0  healthy
all_true     [0, 500, 0]  PSI=0.0  healthy
```

The tracked drift fixture sets the feature to true, but its Phase 11 expected-breach table omits the
feature. Downstream score drift happened to detect that full fixture; the named input signal still
made a false healthy claim.

**Smallest correct remediation — XHigh:** represent booleans with explicit false/true buckets,
preferably a dedicated boolean/categorical JS profile. Regenerate the baseline/bundle and add a
production-path regression showing a baseline-like mixture remains healthy while all-false and
all-true shifts breach. Reconcile the Phase 11 signal evidence after regeneration.

**Batch B result:** `modelguard.baseline-profile.v2` represents the boolean with explicit false and
true buckets and the production monitor evaluates categorical JS distance. The current verification
bundle was regenerated, the requested healthy/all-false/all-true production regressions pass, and
historical Phase 11 evidence is truthfully qualified rather than rewritten.

## Medium findings

| ID | Finding and evidence | Required remediation | Effort |
| --- | --- | --- | --- |
| M12-01 | Per-feature missingness is unreachable. `PredictionEventV1` requires every feature (`src/modelguard/inference/events.py:57-81`); classification rejects missing fields before `evaluate_missingness_signal` (`src/modelguard/monitoring/events.py:363-382`, `src/modelguard/monitoring/drift.py:258-320`). A 100-record probe with five missing `amount` fields produced 5 rejects while accepted-feature missingness remained `0.0/valid`. | Either attribute missing/null fields from raw parsed records before strict rejection with explicit denominators, or narrow the contract to generic schema-rejection monitoring. Add an end-to-end missing-field snapshot test. | XHigh |
| M12-02 | Delayed labels have no temporal eligibility check. `src/modelguard/monitoring/performance.py:46-68` validates UTC but not `event_timestamp <= labeled_at <= cutoff`. A production-path probe joined 500 labels dated in 2099 to 2026 events and returned `warning`, `adequate_labels_cost_delta_evaluated`, `metrics_computed=True`, and AP `1.0`. | Pass an explicit logical cutoff, classify early/future labels, bind the cutoff/classification into report identity, and test labels before events and after cutoff. | XHigh |
| M12-03 | `LocalRunStateStore` performs read/compare/replace without a process lock (`src/modelguard/monitoring/persistence.py:311-317`). A forced interleaving let both writes return true and the older attempt win. | Hold the existing process-safe lock across read/compare/write, align same-timestamp conflict behavior with AWS, and add a forced multiprocess interleaving test. | XHigh |
| M12-04 | `report_id` identifies semantic inputs, not persisted report content (`src/modelguard/monitoring/report.py:86-159`). Mutating both duplicated drift states from degraded to healthy left the ID unchanged and parsed successfully. | Add and validate a canonical report-content digest or require an independently trusted expected object digest; document the semantic-input role of `report_id`. | XHigh |
| M12-05 | The ignored bundle used by `make release-gates` is internally valid but not bound to current HEAD or `uv.lock`. The audit observed `bundle_git_sha_matches_head=False`, `bundle_uv_lock_matches_head=False`, while source-package lineage still matched. `Makefile:161-163` verifies only trusted-origin/internal consistency. | Add a current-source/lock binding mode to the release verification and regenerate the bundle when it fails. Keep internal bundle verification distinct from release-candidate provenance. | XHigh |
| M12-06 | Normal destroy apply paths do not call the existing `verify-empty-managed-state` guard (`.github/workflows/destroy-demo.yml:295-311`, `scripts/safe_destroy.sh:269-278`, `scripts/terraform_demo_guard.py:1333-1336`). Service inventory cannot prove every Terraform state entry is gone. | Stream `terraform state pull` directly into the bounded verifier immediately after apply and before inventories; suppress raw state and require ordering in workflow/helper tests. | XHigh |
| M12-07 | The tracked Phase 10 evidence boundary contradicts the closure report. `reports/evidence/phase-10/README.md:29-32` says live evidence remains absent; `reports/phase-10.md:608-680` and `tasks/phase_status.json:52-62` claim completed live deployment/teardown. The report is a tracked sanitized narrative with hashes, but no standalone machine-checkable manifest binds the state-zero result and both teardown inventories to the corresponding private receipt checksums. | Add value-free source/run/plan/inventory/state-zero summaries bound to encrypted receipt hashes, update the evidence README, and describe live acceptance as private/external attestation until locally checkable. Correct the retained-resource wording in `ACCEPTANCE_CRITERIA.md:164-166`. | Max |
| M12-08 | The required CI Mypy command omits `scripts/phase11_demo.py`, `scripts/export_portfolio_architecture.py`, and `scripts/validate_portfolio.py` (`.github/workflows/ci.yml:40-59`) even though `make typecheck` covers them (`Makefile:82-103`). All three currently type-check, so this is latent false confidence. | Make CI invoke the canonical Make target or derive both commands from one checked list; add a parity regression. | XHigh |

## Low findings

| ID | Finding | Remediation | Effort |
| --- | --- | --- | --- |
| L12-01 | The repeated-stationary integration test reuses seed `8080`, so adjacent windows contain identical rows (`tests/integration/test_monitoring_phase05.py:58-66`, `:153-175`). A separate probe evaluated 30 distinct-seed windows at `n=500` and 30 at `n=1000`; all 60 were healthy and the maximum prediction-score PSI was `0.0751`, below the `0.10` warning boundary. | Parameterize the helper seed and use independent samples for repeated stationary windows. | XHigh |
| L12-02 | Teardown's “every namespace” wording is broader than inventory: ENIs and network ACLs are not queried (`scripts/verify_aws_teardown.sh:211-242`). | Query exact pre-destroy identities including ENIs/NACLs, or narrow the public claim. | XHigh |
| L12-03 | Notification documentation says the workflow does not receive the subscriber address (`docs/CICD_SECURITY.md:198-211`, `reports/phase-10.md:648-651`), but `scripts/notification_enrollment.py:73-87`, `:170-181` transiently receives and validates it without logging/persisting it. | State the actual in-memory-only boundary and remove unused subscription-read permission if practical. | XHigh |
| L12-04 | CI Terraform validation omits the retained audit-bootstrap root (`.github/workflows/terraform-plan.yml:43-54`). It validated locally in this audit. | Add pinned, backend-disabled init/validate for `infrastructure/audit-bootstrap`. | XHigh |
| L12-05 | The workflow calls `uvx --from yamllint==1.37.1` while yamllint is absent from `uv.lock` and the security-tool lock (`.github/workflows/ci.yml:149-150`). The top-level version is pinned, but artifact/transitive resolution is not repository-locked. | Put yamllint in the locked dev environment or add it to the verified tool lock. | XHigh |
| L12-06 | `FILE_MANIFEST.txt` currently has exact sorted parity, but no canonical release/CI target enforces parity. | Add a fail-closed parity command to `make release-gates` and CI. | XHigh |
| L12-07 | Portfolio validation failure strings can include resolved absolute paths (`scripts/validate_portfolio.py:168-178`, `:196-202`, `:479-495`). Success output is bounded. | Emit repository-relative locations and bounded I/O reasons; add a private-path failure regression. | XHigh |
| L12-08 | “Held-out test evaluated once” is guaranteed once per training invocation, not once for the repository lifetime (`PROJECT_SPEC.md:25`, `ACCEPTANCE_CRITERIA.md:12-13`, `docs/CASE_STUDY.md:35-36`, `portfolio/claims-ledger.md:17`). Phase 11 and Phase 13 intentionally reran the same deterministic split; no evidence of test-driven retuning was found. | Change public wording to “once per training invocation, after threshold lock,” or reserve a genuinely untouched final holdout. | XHigh |
| L12-09 | Three tracked Phase 10 documents contain the actual-looking runner ingress `/32` rather than a value-free identity (`reports/phase-10.md:640-651`, `ACCEPTANCE_CRITERIA.md:190-191`, `checklists/PHASE_10.md:48-49`). The report elsewhere says raw addresses were not emitted. The value appears ephemeral and the demo was destroyed, so this is Low rather than an active credential finding. | Replace current-tree values with “exact reviewed `/32`” or a one-way evidence identity. Record the already-published history exposure as a residual; do not rewrite published history. | XHigh |

## Acceptance-criteria gap map

| Acceptance area | Audit status | Evidence/gap |
| --- | --- | --- |
| Data/training leakage and metrics | **Pass** | Split-before-fit, train-only calibration, validation-only threshold, and exact metric recomputation passed. L12-08 wording now accurately says once per invocation after threshold lock. |
| Model-bundle release provenance | **Pass for current non-release use / accepted risk** | Internal checksum/schema/smoke verification passed. M12-05 forbids treating the ignored dirty-source bundle as future release provenance and requires clean regeneration before publish/deploy. |
| Drift monitoring | **Pass with accepted boundary** | H12-06 is closed; boolean JS detects both extreme shifts. M12-01 is accurately narrowed: missing required v1 fields are schema rejections, not per-feature attribution. |
| Label-backed performance | **Pass with accepted local-only risk** | Cost-delta math and no-label honesty are sound. M12-02 documents that the trusted synthetic label source owns temporal eligibility. |
| Report/schema/dashboard evidence | **Pass with accepted integrity boundary** | H12-03/H12-04 are closed. M12-04 documents semantic `report_id` versus external file/object integrity evidence. |
| AWS one-shot monitoring | **Pass for the audited High boundaries** | H12-03/H12-05 are closed: malformed GZIP/JSON produces the canonical failed result and snapshots use finite physical hour prefixes with global limits. |
| Terraform/IAM least privilege | **Pass for Batch A; final audit pending** | H12-02 is repaired with exact account/Region ARN patterns, request/resource tags, and a deny boundary. Final Ultra verification remains deferred until all High findings are closed. |
| Protected deployment/destroy | **Pass with accepted future-hardening risk** | H12-01 is closed. Historical state-zero/service evidence exists; M12-06 records the missing immediate ordinary-workflow state verifier without weakening the disposable-resource claim. |
| Teardown evidence | **Pass as private/external attestation** | The evidence README's live section explicitly supersedes historical local-only text. Source/plan hashes and bounded results are public; raw receipt chains remain encrypted/private under M12-07. Phase 12 made no cloud call. |
| CI/CD gates | **Pass with accepted parity risk** | H12-01 is closed. Required checks and all current local type checks pass; M12-08 records the inline CI/Make script-list divergence. |
| Containers/security scanners | **Pass for current static gate** | Non-root/container controls are present; Bandit, hashed pip-audit, actionlint, ShellCheck, Checkov, Gitleaks, and Trivy passed. Scanner success does not mitigate H12-01/H12-02. |
| Portfolio assets/media | **Pass structurally; claims partial** | Media/link/hash/privacy checks pass. CL-05, CL-13, CL-21, CL-22, and CL-23 need the boundaries below. |

## Portfolio credibility review

No fabricated screenshot, video, GIF, metric, cloud endpoint, or production-readiness claim was
found. The synthetic-data, temporary-cloud, non-HA, no-label, no-causation, and no-business-impact
boundaries are consistently disclosed. Twenty-five of the thirty ledger entries remain supported
within their existing boundaries.

The following entries require correction or qualification:

| Claim | Audit disposition |
| --- | --- |
| CL-05 | **Supported with boundary.** Leakage order is supported and public wording now says once per training invocation after threshold lock. |
| CL-13 | **Supported with boundary.** PSI/JS/score/decision/schema-state mechanics and the boolean signal are supported; missing required v1 fields are explicitly schema-rejected rather than attributed per feature. |
| CL-21 | **Partial.** OIDC subjects, deploy-role EC2 containment, and shell-safe dispatch handling are evidenced after Batch A; CI Mypy still omits three scripts under M12-08. |
| CL-22 | **Externally/private attested.** The Phase 10 report records live readback; the tracked evidence index still says live evidence is absent. |
| CL-23 | **Externally/private attested.** The report records zero disposable residuals, but the tracked sanitized state/inventory bindings are absent and retained-resource wording conflicts. |

CL-29's media files, hashes, formats, dimensions, and durations passed automated validation. The
“same recording excerpt” assertion remains a documented human-review claim; the automated validator
does not independently prove derivation.

## Teardown and security checklist

- [x] No AWS/GitHub/Terraform mutation occurred during Phase 12.
- [x] Tracked worktree and Git integrity were clean before report generation.
- [x] No tracked Terraform state, plan, key, environment-secret file, scanner database, or temporary
  Terraform directory was found.
- [x] Full-history Gitleaks found one exact bounded/accepted detector false positive and zero
  unaccepted findings; current-worktree Gitleaks found zero.
- [x] The basic secret/file defense passed; no approved AWS account identifier was found in tracked
  content.
- [x] Current public evidence is value-free; L12-09 removed the raw runner `/32` from the current
  tree and records the immutable published-history exposure without rewriting it.
- [x] Exact OIDC audience/subject structure and separate plan/deploy roles exist by static inspection.
- [x] Deploy-role EC2 least privilege passes the Batch A static, semantic-denial, Terraform, and
  Checkov gates; final Ultra verification remains pending.
- [x] Protected destroy shell boundary passes the parsed-workflow and adversarial `$()` regressions.
- [x] Corrupt GZIP/deep JSON is bounded across local, AWS, persistence, and dashboard boundaries.
- [x] External monitoring artifacts use one strict duplicate/non-finite/nesting-safe model loader.
- [x] AWS monitoring scans only finite window-derived hour prefixes under shared global budgets.
- [x] Boolean drift uses explicit false/true baseline buckets and categorical JS distance.
- [x] M12-06 is accepted with explicit scope: historical state-zero proof is retained externally;
  the ordinary workflow's missing immediate verifier remains future hardening.
- [x] L12-02 is accepted with explicit scope: authoritative parent/service/tag inventories prove the
  historical disposable/billable boundary; no dedicated ENI/NACL query is claimed.
- [x] M12-07 is accepted with explicit privacy scope: bounded public hashes/results are reviewable,
  while raw state/inventory receipt chains remain encrypted/private.
- [x] Retained state/audit S3, KMS, and CloudTrail resources are intentionally outside disposable
  teardown and may continue to incur cost. IAM/OIDC controls and the Budget also remain retained;
  the Budget is alerting, not a hard cap. Any pre-existing human-owned ACM certificate or
  SecureString is likewise outside demo teardown.

## Validation evidence

Preserved canonical gate evidence:

- Batch A invoked `make release-gates` exactly once. Ruff, strict Mypy, and all 604 tests ran at
  83.56% coverage; 603 tests passed and one exact suppression-registry assertion failed because it
  still expected the pre-boundary annotation count (`61` instead of `67`).
- The registry invariant was corrected and its focused regression passed. Every not-yet-run or
  directly affected gate component passed, including the affected Checkov scan with 200 passed and
  zero failed checks. The canonical target was deliberately not restarted.
- Batch B did not invoke `make release-gates`. It preserved the exact-once evidence and used focused
  tests and permitted non-canonical quality targets.

Final-audit execution note: a backtick-delimited phrase in one intended read-only `rg` pattern was
interpreted by Bash as command substitution and unintentionally started a second
`make release-gates` attempt. It was detected and its process group was terminated before the
repository security-scan and portfolio stages. The swallowed intermediate output is not used as
evidence, no passing receipt was produced, and the original Batch A canonical receipt remains
unchanged. This is a recorded procedural deviation from the requested no-rerun discipline, not a
replacement or fabricated canonical result. No further canonical invocation occurred.

The preserved canonical receipt therefore remains a truthful failed-composite receipt with a
repaired, narrowly verified sole cause; it is not represented as a full passing rerun:

```text
make release-gates
RESULT — 604 collected; 603 passed; 1 stale suppression-registry assertion failed;
         83.56% branch-aware coverage. The exact focused repair passed; no canonical rerun.
```

Focused, overlapping workstream evidence (not an additive unique-test count):

```text
Application selection: 210 passed; additional Phase 10 runtime/publisher/AWS-monitor selection: 88 passed.
ML/statistical selection: 93 passed.
AWS/Terraform/CI/governance selection: 250 passed.
Batch B H12-03/H12-04/H12-05/H12-06 selections: 4/27/6/2 passed respectively.
Batch B affected application/monitoring selection: 166 passed.
Batch B Phase 11/schema/runtime selection: 41 passed.
Strict Mypy: 77 source files passed.
Terraform fmt -check: passed.
Terraform validate: audit-bootstrap, bootstrap, and demo roots passed locally.
bash -n and ShellCheck over tracked shell: passed.
git fsck --full --strict --no-reflogs --unreachable: structurally passed; two unreachable UTF-8
  blobs were reported. They are absent from every ref and current worktree path, closely match old
  Phase 13 portfolio-document variants, and have object mtimes predating Batch B. A dedicated
  redacted Gitleaks scan found zero findings. They were preserved rather than pruning potentially
  user-owned recovery data.
Monitoring JSON Schema export parity: passed.
FILE_MANIFEST.txt: sorted, unique, exact parity across 348 candidate paths after adding this report.
```

Independent metric recomputation against the verified bundle also matched exactly: 750 test rows,
prevalence `0.188`, AP `0.40842191798974226`, AP lift `2.1724570105837353`, ROC-AUC
`0.7291222676402427`, Brier `0.13517268524374973`, log loss `0.42991718637314047`, confusion
matrix `TN/FP/FN/TP=61/548/2/139`, and synthetic cost `568` or `0.7573333333333333` per event.
The focused ML command covering generation, split, evaluation, bundle, drift, performance, events,
integration, and report contracts was:

```bash
uv run --frozen --no-sync pytest -q --no-cov -p no:cacheprovider \
  tests/unit/test_data_phase02.py tests/unit/test_split_pipeline_phase02.py \
  tests/unit/test_evaluate_baseline_phase02.py tests/unit/test_bundle_phase02.py \
  tests/integration/test_training_workflow_phase02.py \
  tests/unit/test_monitoring_drift_phase05.py \
  tests/unit/test_monitoring_performance_phase05.py \
  tests/unit/test_monitoring_events_state_phase05.py \
  tests/integration/test_monitoring_phase05.py \
  tests/contract/test_monitoring_report_contract_phase05.py
```

Result: 93 passed. The delayed-label and distinct-seed stationary observations above came from
read-only production-path probes using the same locked environment; no generated result was treated
as a passing committed regression.

The local Terraform validation binary was 1.15.8 while workflows pin 1.10.5; this is useful schema
evidence, not exact pinned-tool evidence. The canonical security gate used the repository-verified
scanner identities listed above.

## Remediation batches

1. **Batch A — Max: AWS authority containment — completed.** H12-01 and H12-02 now have adversarial
   workflow-expression policy tests and semantic IAM denial tests.
2. **Batch B — XHigh: monitoring correctness and artifact boundaries — completed for the authorized
   scope.** H12-03 through H12-06 are repaired and regression-tested. M12-01 through M12-04 remain
   explicitly queued; they were not part of the user-authorized Batch B scope.
3. **Former Batch C candidates — dispositioned.** M12-06/M12-07 and L12-02 are accepted with explicit
   historical/private-evidence boundaries; L12-03 is fixed in current documentation. They remain
   optional hardening, not hidden release claims.
4. **Former Batch D candidates — dispositioned.** M12-05/M12-08 and the remaining Low release-tool
   items are accepted with compensating local gates; L12-08/L12-09 are fixed in the current claims
   and privacy tree.

All initial High findings have focused regressions, every Medium/Low item has a final disposition,
and the final Ultra audit passes without inventing a canonical rerun. Phase 12 is complete with the
accepted MVP risks above; none is represented as production-grade coverage.
