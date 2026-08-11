# Demo Video Script — 3 to 5 Minutes

The exact Phase 11 commands, expected machine-readable output, evidence paths, and claim boundaries
are in [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md). Use that runbook for new evidence; the older Phase 07
container commands below remain useful only when a live Compose walkthrough is desired.

## 0:00–0:25 — The problem

Show the architecture diagram and say:

> Deploying a model is not the end of the work. The real challenge is knowing which version is
> running, whether the service is healthy, and whether the data has changed in a way that threatens
> model decisions.

## 0:25–0:55 — The system

Briefly show:

- FastAPI.
- The MLflow run.
- Terraform modules.
- GitHub Actions checks.

Do not spend a long time scrolling through code.

## 0:55–1:30 — Healthy drift state

```bash
PHASE11_ANCHOR="$(date -u -d '1 minute ago' +%Y-%m-%dT%H:%M:00Z)"
make phase11-demo-local \
  PHASE11_RUN_ID=phase11-recording \
  PHASE11_ANCHOR="$PHASE11_ANCHOR"
```

Show the dashboard with separate states: `run=succeeded`, `data_quality=valid`, `drift=healthy`, and
`performance=unknown` when labels are unavailable. Also show the report target model and accepted
target count.

## 1:30–2:20 — Drift injection

The same Phase 11 command produces the separate non-overlapping drifted window after capturing the
healthy dashboard evidence. Open the generated baseline and drifted summaries and their immutable
HTML reports; do not run an additional mixed-window traffic command.

Show:

- The top drifting features.
- `run=succeeded`, `data_quality=valid`, `drift=degraded`, and `performance=unknown` without labels.
- The HTML incident report.
- An SNS email or CloudWatch alarm, if configured.

For the Phase 11 local recording, show
`artifacts/phase-11-evidence/phase11-recording/summary.json`, the two report-backed dashboard
snapshots, and the real Streamlit in-process render results. SNS/CloudWatch remain unconfigured
locally and must not be implied by this run.

## 2:20–3:10 — Engineering evidence

Briefly show:

- GitHub Actions tests, security, and Terraform checks.
- ECR image SHA.
- ECS deployment health.
- Terraform plan or module tree.
- OIDC without AWS access keys.

## 3:10–3:50 — Recovery

Demonstrate either:

- Rolling back an ECS task definition after a deliberately bad deployment, or
- Promoting a validated model bundle and showing the readiness/model-version change.

The Phase 11 local path uses the second option: it verifies and manually promotes `1.0.1`, retains
`1.0.0` as previous, and proves readiness/version. Do not imply automatic retraining, a metric-based
selection, or that promotion fixes the observed drift; the deployment-control story is separate.

## 3:50–4:10 — Outcome

> The project turns an ML model into a deployable, observable, and auditable AWS service. It presents
> input and prediction-distribution changes as investigation evidence—not as a claim that accuracy
> declined—and includes CI/CD and infrastructure as code.

## Required screenshots

1. Architecture diagram.
2. MLflow metrics and artifacts.
3. API response and health status.
4. Healthy dashboard.
5. Degraded dashboard.
6. HTML incident report.
7. Green GitHub Actions checks.
8. Terraform, IAM, and ECS evidence.
