# Demo Video Script — 3 to 5 Minutes

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
curl -s http://<api>/health/ready | jq
uv run python scripts/send_demo_traffic.py --scenario baseline --count 600 \
  --window-end 2026-01-01T01:00:00Z
uv run python -m modelguard.monitoring.cli run \
  --window-end 2026-01-01T01:00:00Z --as-of 2026-01-01T01:10:00Z
```

Show the dashboard with separate states: `run=succeeded`, `data_quality=valid`, `drift=healthy`, and
`performance=unknown` when labels are unavailable. Also show the report target model and accepted
target count.

## 1:30–2:20 — Drift injection

```bash
uv run python scripts/send_demo_traffic.py --scenario drifted --count 600 \
  --window-end 2026-01-01T02:00:00Z
uv run python -m modelguard.monitoring.cli run \
  --window-end 2026-01-01T02:00:00Z --as-of 2026-01-01T02:10:00Z
```

Show:

- The top drifting features.
- `run=succeeded`, `data_quality=valid`, `drift=degraded`, and `performance=unknown` without labels.
- The HTML incident report.
- An SNS email or CloudWatch alarm, if configured.

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

Do not imply automatic retraining. Explain that promotion is controlled.

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
