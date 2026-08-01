# Phase 00 Architecture and Specification Review

- Review completed (UTC): 2026-08-01T20:49:25Z
- Phase boundary: review/specification repair only
- Application implementation status: not started
- AWS/Terraform/Docker/workflow mutations: none
- Commit: none

## Executive verdict

**READY WITH REQUIRED CHANGES — changes applied. Phase 01 decision: GO.**

The planned component choices are proportionate to a finishable production-style synthetic MLOps
demo. Four independent review workstreams initially returned NO-GO because several cross-phase
contracts required implementers to guess. Phase 00 repaired those contracts in governing documents,
phase prompts, checklists, configuration examples, ADRs, and evidence templates. No application,
container, Terraform-resource, workflow, or AWS implementation was pulled forward.

This is a specification-readiness GO, not an implementation or release claim. The current shell has
Python 3.14.4 and no `uv`; Phase 01 must establish Python 3.12 and the committed lock before its gate.

## Review method and material assumptions

The required documents were read completely in the user-specified order. The requested root-level
review-notes path was absent; the manifest-backed file now named `docs/00_REVIEW_NOTES.md` was read
in that fifth position. This path discrepancy was treated as invocation context, not repaired by
duplicating the document because repository references use the canonical `docs/` path.

Afterward, all 97 initial repository paths and all 77 non-empty files (3,235 initial lines) were
inspected. The parallel workstreams were:

1. Architecture/data flow and failure behavior.
2. MLOps/statistics and claim validity.
3. AWS/IAM/networking/secrets/teardown.
4. Testing/delivery/portfolio and cross-file synthesis.

Material assumptions:

- Phase 00 may repair documentation, contracts, checklists, templates, and existing configuration
  inconsistencies, but may not implement future-phase behavior.
- The unpacked launch kit intentionally has no `.git` directory; Phase 00 did not initialize one.
- No external credentials, deployed resources, screenshots, generated models, or future-phase
  artifacts were assumed to exist.
- Exact synthetic feature distributions and model hyperparameters remain Phase 02 implementation
  choices, but their ownership, deterministic conventions, lineage, and consumer boundaries are now
  fixed.

## Blocking findings and repairs

### P00-01 — First AWS deployment could start an unreadable API

**Initial severity:** critical. **Status:** contract repaired.

The old sequence applied ECS before a bundle and active pointer existed, while readiness correctly
failed without them. The repaired contract uses two reviewed saved plans: prerequisites with
runtimes/schedule disabled; immutable image/model/pointer verification; then digest-pinned activation.
Model pointers include semantic version plus manifest digest, startup loads once, and promotion or
rollback forces a controlled ECS deployment. No ad hoc Terraform targeting is allowed.

Primary evidence: `ARCHITECTURE.md`, `prompts/08_TERRAFORM_AWS.md`,
`prompts/10_AWS_DEPLOYMENT.md`, `docs/08_AWS_DEPLOYMENT_ORDER.md`.

### P00-02 — Monitoring counts and lateness were not implementable

**Initial severity:** high. **Status:** contract repaired and scope reduced.

The old monitor classified both late and outside records but omitted outside records from its count
equation, and inference events had no trustworthy delivery-arrival timestamp. Grace is now only a
window-finalization guard. Every run freezes its input snapshot and reconciles record counts exactly:

```text
raw = rejected + outside_window + known_non_target + duplicate + accepted_target
```

Firehose delivery and S3-prefix freshness own delivery-delay evidence. The MVP makes no row-level
delivery-lateness claim.

Primary evidence: `ARCHITECTURE.md`, `prompts/04_PREDICTION_LOGGING.md`,
`prompts/05_DRIFT_MONITOR.md`, `checklists/PHASE_05.md`.

### P00-03 — Rolling deployment conflicted with version-purity rules

**Initial severity:** high. **Status:** contract repaired.

Each run now snapshots one exact target event/model/manifest/input-schema identity. Verified known
non-target events are counted/excluded and warn rather than poisoning target metrics; unknown or
conflicting identities invalidate data quality. Baseline identity derives from the verified target
bundle, and monitoring configuration is a run-level canonical hash. This preserves pure metrics
without multi-model report fan-out or an unavoidable blind rollout window.

### P00-04 — Performance states had names but no state-driving rule

**Initial severity:** high. **Status:** contract repaired with a bounded synthetic heuristic.

Phase 02 stores held-out locked-threshold synthetic cost per event. With adequate valid local labels,
Phase 05 compares current labeled-subset cost per event with that reference. Versioned delta defaults
are healthy below 0.10, warning from 0.10 to below 0.25, and degraded at or above 0.25. Other metrics
remain diagnostic. No label source is unknown; an inadequate configured source is pending; conflicts
or unknown label schema are unknown. Wording must identify the labeled subset and synthetic policy;
it is not a significance test, full-window guarantee, real economics, or causal accuracy claim.

### P00-05 — Statistical reproducibility relied on unspecified defaults

**Initial severity:** high. **Status:** contract repaired.

The Phase 02 contract now fixes five shuffled seeded stratified folds, sigmoid calibration,
`ensemble=True`, the thousandth threshold grid/tie order, inclusive decision rule, reliability-bin
edges, AP-lift definition, and JSON-null rules for undefined metrics. Prediction-score and decision
distribution references are explicitly generated from training-reference rows only as drift
baselines, never as training-performance evidence. Canonical hashes record algorithm, ordering,
version, and exclusions.

### P00-06 — Shared-token transport and ownership were unsafe/ambiguous

**Initial severity:** critical. **Status:** contract repaired.

Every AWS ALB requires a non-world CIDR. Preferred `https_token` mode adds ACM HTTPS and a
constant-time bearer-token check on prediction; only a pre-created SSM SecureString ARN enters
Terraform, never token bytes. Token-exempt health routes are minimal and `/metrics` is not publicly
routed. Temporary `http_cidr_only` transmits no reusable token and cannot support authentication or
secure-transport claims. This remains a synthetic demo gate, not an auth platform.

### P00-07 — Prometheus metrics had no path into CloudWatch alarms

**Initial severity:** high. **Status:** contract repaired without adding a service.

Prometheus remains local/test-facing. AWS uses native managed metrics plus a small fixed set of
low-cardinality EMF records through stdout/CloudWatch Logs. The Phase 08 alarm matrix must identify a
producible source for every alarm, distinguish Scheduler submission from task completion, and test
missing-data behavior. No ADOT, AMP, or metrics sidecar was added.

### P00-08 — AWS trust, budget, plan, and destroy boundaries were incomplete

**Initial severity:** critical/high. **Status:** governing contracts repaired; implementation owned by
Phases 01 and 08–11.

Human/SSO bootstrap now owns remote state, exact OIDC trust, and a mandatory permission boundary;
demo deploy cannot alter it. Protected main-ref and protected-environment subjects are exact
alternatives, PassRole is scoped, fork PRs receive no AWS identity, budget notification needs a
confirmed noncommitted human destination, raw plans are restricted transfer artifacts, and guarded
destroy must verify exact account/Region/backend/workspace/tags plus post-destroy inventory. The
existing Phase 01/08 scripts are still intentionally skeletons and must be repaired/tested in their
owner phases.

### P00-09 — Public/demo wording and small configuration contracts contradicted the design

**Initial severity:** medium. **Status:** repaired.

- Removed the misleading dashboard “overall state” and displayed four dimensions.
- Replaced “Production-Ready” marketing wording with “production-style synthetic demo.”
- Gave the baseline/drift demo separate explicit windows and sample headroom.
- Standardized local events on JSONL and deferred Parquet.
- Aligned monitoring minimum from 200 to 500.
- Aligned the sample Codex effort from High to XHigh.
- Corrected the Phase 11/13 branch labels and incident-state template.
- Restricted the Python package range to 3.12 and expanded tfvars ignore coverage.

## Recommended scope reductions adopted

- JSONL is the only local prediction-event format; Parquet is deferred.
- Firehose physically partitions by UTC date/hour; dynamic model-version partitioning is deferred.
- Grace delays window finalization; row-level late-delivery measurement is deferred.
- A monitor run targets one explicit model identity; multi-version fan-out reports are deferred.
- Model loading is startup-only; hot reload is deferred.
- PSI and JS distance remain the drift core; KS and statistical significance claims are deferred.
- CloudWatch uses native metrics plus EMF; no Prometheus collector/sidecar/service is added.
- AWS labels remain out of scope; the optional label-backed fixture is local and synthetic.
- One NAT and desired count one remain explicit non-HA demo choices; no interface-endpoint/HA
  expansion was added.

## Intentionally deferred beyond MVP

- Full authentication/identity platform, public anonymous service, and permanent hosting.
- Row-level Firehose delivery-lateness SLA and exactly-once alert delivery.
- Automatic retraining, promotion, rollback, causal diagnosis, or drift-as-accuracy conclusions.
- Model signing/Object Lock/custom KMS trust system; protected publisher IAM is the MVP trust boundary.
- Statistical significance/multiple-testing correction for the label-backed synthetic heuristic.
- Hosted MLflow, online label collection, database, feature store, EKS, Kafka/MSK, Airflow, LLMs,
  multi-region operation, second NAT, and always-on HA capacity.

## Risk register

| Risk | Severity | Likelihood | Mitigation/contract | Owner phase |
| --- | --- | --- | --- | --- |
| Initial service starts before image/model/pointer prerequisites | Critical | High | Two-stage default-off prerequisite and digest-pinned activation plans | 08, 10 |
| OIDC deploy role can change its own trust or create unbounded roles | Critical | Medium | Bootstrap-owned exact trust and mandatory permission boundary | 08, 09 |
| Token leaks through Terraform/logs or travels over HTTP | Critical | Medium | ARN-only SSM injection; HTTPS-token or tokenless CIDR-only modes | 03, 08, 10 |
| Irreconcilable or version-mixed monitoring reports | High | High | Frozen snapshot, exclusive count equation, explicit target identity | 04, 05 |
| Mutable JSONL/object packaging breaks report/alert idempotency | High | Medium | Canonical record digests, immutable history, conditional monotonic latest/markers | 05, 08 |
| Synthetic performance heuristic is marketed as real degradation | High | High | Labeled-subset wording, claims ledger, fixed synthetic cost reference | 05, 13 |
| Partial labels are selection-biased | Medium | High | Coverage/adequacy diagnostics and explicit residual limitation | 05, 13 |
| CloudWatch alarms exist without data sources | High | High | Native/EMF source matrix and missing-data tests | 03–05, 08 |
| Same semantic model version resolves to changed bytes | High | Medium | Version+manifest identity, no-overwrite publish, post-upload verification | 02, 08–10 |
| Wrong-account/incomplete destroy leaves spend or secret material | High | Medium | Exact guards, reviewed plan hash, service/tag inventory, retained-bootstrap list | 08, 10, 11 |
| Budget exists but reaches no person | High | Medium | Required confirmed noncommitted budget destination | 08, 10 |
| Dropped events bias drift evidence | Medium | Medium | Separate producer/delivery/freshness signals and best-effort limitation | 04, 08, 13 |
| One NAT/task interrupts service or replacement | Medium | Medium | Explicit non-HA limitation; no availability claim | 08, 13 |
| Setup/scanner skeleton executes unverified installers or prints matches | High | Medium | Phase 01 pins/verifies or makes manual; scanner emits redacted locations | 01 |

## Documentation/configuration edits applied

1. Governing contracts: `PROJECT_SPEC.md`, `ARCHITECTURE.md`, `ACCEPTANCE_CRITERIA.md`.
2. Phase ownership/gates: prompts 01–06 and 08–11; checklists 01–06 and 08–11.
3. Decisions/security/deployment: ADR-002/003/006/007/008 and docs 01/03/04/05/06/08/10.
4. Small configuration contradictions: `.env.example`, `.gitignore`, `pyproject.toml`.
5. Evidence/status surfaces: `templates/INCIDENT_REPORT.md`, `checklists/PHASE_00.md`,
   `tasks/phase_status.json`, `README.md`, and `FILE_MANIFEST.txt`.

No source module, test, Docker file, Terraform resource, GitHub workflow, or AWS state was changed.

## Commands and evidence

| Command/check | Result |
| --- | --- |
| Required ordered `wc -l` + `sed` reads | Pass; all seven documents read completely; canonical review-notes path recorded |
| `rg --files -uu \| sort` plus full `awk`/`sed` reads | Pass; entire launch kit inspected |
| Manifest comparison with `comm -3` | Pass after adding this report; manifest self-exclusion is intentional |
| `bash -n START_HERE.sh scripts/*.sh` | Pass; 7 shell entry points parsed |
| `python3 -m json.tool tasks/phase_status.json` | Pass |
| Python `tomllib` parse of `pyproject.toml` and `.codex/config.toml` | Pass |
| `./scripts/check_no_secrets.sh` | Pass for current unpacked files; history scan unavailable without Git |
| Cross-file `rg` contradiction/contract scans | Pass; no stale 200 default, High example, production-ready claim, old count equation, or positive overall-state claim |
| `shellcheck START_HERE.sh scripts/*.sh` | Skipped: shellcheck is not installed |
| Ruff/Mypy/Pytest/Bandit/pip-audit | Not run: Phase 00 changed no implementation; `uv`/Python 3.12 environment and lock are Phase 01 outputs |
| Git status/diff | Unavailable: the launch kit is not yet a Git repository; Phase 00 did not initialize or commit |
| Docker/Terraform/AWS commands | Not run, by Phase 00 boundary |

Test count: **0 application tests run**. This is an explained Phase 00 skip, not a passing application
claim. Document/schema/shell/security checks above are the Phase 00 gate.

## Residual risks and owner-phase gates

- The existing setup and basic secret-check scripts remain planning skeletons; Phase 01 must fix the
  pinned-install/redacted-output requirements before its checklist can pass.
- Python 3.12 and `uv` are not available in the current shell. Phase 01 cannot complete its validation
  gate until the user provisions them; no dependency sync was attempted in Phase 00.
- The cost-delta policy is deliberately heuristic and synthetic. Phase 02/05 must test exact
  boundaries; Phase 13 must retain the labeled-subset limitation.
- Atomic local/S3 status and transition behavior, SSM secret injection, EMF schemas, IAM boundaries,
  two-stage Terraform, and guarded destroy are specifications only until their named phases implement
  and evidence them.
- No Git history existed, so tracked-history secret scanning and a true diff review remain unavailable.

No unexplained Phase 00 failure remains.

## Phase 01 decision and next manual action

**GO — Phase 01 may begin.**

First review this report and the checked `checklists/PHASE_00.md`. Then provision a trusted `uv`
installation and Python 3.12 without writing credentials, and run:

```bash
./scripts/run_phase.sh 01 xhigh
```

Phase 01 must stop after its own gate. Suggested manual commit message for this phase:

```text
phase 00: repair launch-kit contracts and approve phase 01
```
