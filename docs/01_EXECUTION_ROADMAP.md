# Complete Execution Roadmap

> The intended final order runs Phase 13 before Phase 12, despite the original file numbering.

## Before implementation: Phase 00 — Architecture Review

**Mode:** Sol Ultra

**Objective:** Review architecture, security, testing, and scope reduction through independent
workstreams without writing application code.

**Prompt:** `prompts/00_ULTRA_ARCHITECTURE_REVIEW.md`

After the review, change documentation only when the recommendations improve quality without
expanding the project.

---

## Phase 01 — Repository Bootstrap

**Mode:** Sol XHigh

**Deliverables:** Python/uv project, Makefile, quality tooling, configuration, test skeleton, and
README skeleton.

**Commands:**

```bash
./scripts/run_phase.sh 01 xhigh
make verify
git add -A && git commit -m "phase 01: bootstrap repository and quality gates"
```

Do not advance until setup, lint, type checking, and tests work, even if the test suite is still
small.

---

## Phase 02 — Data and Training

**Mode:** Sol XHigh; use Max if unresolved statistical, leakage, or calibration issues remain.

**Deliverables:** Generator, validation, sklearn Pipeline, metrics, MLflow, model bundle, and
baseline profile.

**Commands:**

```bash
./scripts/run_phase.sh 02 xhigh
make train
make verify
```

**Early evidence:** Keep a screenshot of MLflow and the metrics, but do not treat it as the final
portfolio presentation.

---

## Phase 03 — FastAPI Inference Service

**Mode:** Sol XHigh

**Deliverables:** API contracts, model loader, predictor, health/version/metrics endpoints, and
tests.

**Commands:**

```bash
./scripts/run_phase.sh 03 xhigh
make api
curl -s http://localhost:8000/health/ready | jq
```

---

## Phase 04 — Prediction Event Logging

**Mode:** Sol XHigh

**Deliverables:** Event schema, local sink, Firehose sink abstraction, retry/failure metrics, and
mock tests.

**Commands:**

```bash
./scripts/run_phase.sh 04 xhigh
make verify
```

---

## Phase 05 — Drift Monitoring and Incident Reports

**Mode:** Sol Max

**Rationale:** This is the most important logic-heavy phase. It requires correct calculations,
edge-case handling, and stable drift tests.

**Deliverables:** PSI/JS logic, insufficient-data behavior, reports, state machine, and alert
deduplication.

**Commands:**

```bash
./scripts/run_phase.sh 05 max
make monitor
make verify
```

Then run a stationary dataset and a shifted dataset and confirm that the tests prove the expected
state transition.

---

## Phase 06 — Dashboard

**Mode:** Sol Max

**Deliverables:** Clean Streamlit UI, storage repository, charts, and honest stale/unknown states.

**Commands:**

```bash
./scripts/run_phase.sh 06 max
make dashboard
```

---

## Phase 07 — Docker and Local End-to-End

**Mode:** Sol XHigh

**Deliverables:** Non-root Dockerfiles, Compose, local smoke scripts, and image scans.

**Commands:**

```bash
./scripts/run_phase.sh 07 xhigh
docker compose up --build -d
./scripts/smoke_local.sh
```

Do not begin AWS work until the complete local scenario passes.

---

## Phase 08 — Terraform AWS Architecture

**Mode:** Sol Max

**Rationale:** IAM, networking, ECS, ALB, Firehose, S3, scheduling, alarms, state, outputs, and their
interactions require deep review.

**Deliverables:** Modules, demo environment, state bootstrap, and deployment/destruction plans.

**Preferred interactive command:**

```bash
codex
```

Then select `/model` → Sol → Max and send:

```text
Read AGENTS.md and prompts/08_TERRAFORM_AWS.md. Execute only this phase. Do not run terraform apply.
```

Afterward, run:

```bash
terraform fmt -recursive infrastructure
terraform -chdir=infrastructure/environments/demo init -backend=false
terraform -chdir=infrastructure/environments/demo validate
make security-tools-bootstrap
make security-scan
```

---

## Phase 09 — GitHub Actions and DevSecOps

**Mode:** Sol Max

**Deliverables:** CI, infrastructure planning, image builds, OIDC deployment, protected manual
deployment, and smoke/rollback evidence.

**Important:** Never run `terraform apply` on pull requests.

---

## Phase 10 — Controlled AWS Deployment

**Mode:** Sol Max with human approval for every AWS change.

**Deliverables:** Verified account and Region, bootstrap, a prerequisite plan with runtimes disabled,
digest-pinned images, a verified model/pointer, an activation plan, and healthy ECS services.

This phase requires human review of the saved plan for every stage before apply. Do not use
`terraform -target`.

---

## Phase 11 — Failure and Drift Demo

**Mode:** Sol Max

**Deliverables:** Traffic generator, healthy run, drift injection, degraded status, alert/report,
and either rollback or controlled promotion.

Record the demo video during this phase.

---

## Phase 12 — Final Audit

**Mode:** Sol Ultra

**Objective:** Independently review code, security, Terraform, tests, documentation, and portfolio
content without adding new features.

**Prompt:** `prompts/12_ULTRA_FINAL_AUDIT.md`

Run Phase 13 first. After the Ultra audit, address findings in small XHigh or Max repair batches.

---

## Phase 13 — Portfolio Packaging

**Mode:** Sol XHigh; run before Phase 12.

**Deliverables:** Final README, case study, LinkedIn post, Upwork portfolio copy, Fiverr service
packages, screenshot list, and demo script.

## Suggested branch order

```text
main
phase/01-bootstrap
phase/02-training
phase/03-api
phase/04-events
phase/05-monitoring
phase/06-dashboard
phase/07-local-e2e
phase/08-terraform
phase/09-cicd
phase/10-aws-demo
phase/11-failure-demo
phase/13-portfolio
```

A personal project can use direct commits on `main`, but branches provide a clearer history and make
it possible to present pull requests as portfolio evidence.
