# ModelGuard AI — Product and Engineering Specification

## 1. Product statement

ModelGuard AI is a compact production-style MLOps reliability system that trains and versions a fraud-risk model, serves predictions through a secure API, records inference events, detects input and prediction drift, publishes incident reports, and exposes operational status through a dashboard.

## 2. Primary audience

- CTOs and engineering managers evaluating AWS MLOps capability.
- Clients seeking ML model deployment, CI/CD, observability, drift detection, and infrastructure as code.
- Recruiters evaluating Cloud, DevOps, Data Engineering, and MLOps experience.

## 3. Portfolio message

> From a notebook model to a secure, observable, versioned AWS service with automated quality gates and drift incident handling.

## 4. MVP capabilities

### Data and training
- Deterministic synthetic fraud dataset generator.
- Schema validation and data-quality summary.
- Persisted, hashed, stratified train/validation/test split created before fitting.
- Scikit-learn preprocessing and classification pipeline.
- MLflow experiment tracking in local development.
- Cross-fitted calibration on train only; validation-only cost threshold; held-out test evaluated
  once per training invocation after the threshold is locked.
- Metrics: average precision versus prevalence/lift, ROC-AUC, Brier, log loss, reliability bins,
  precision, recall, F1, confusion matrix, selected threshold, and synthetic cost.
- Versioned model bundle containing model, schema, metrics, threshold, and baseline profile.

### API
- FastAPI service.
- `POST /v1/predict`.
- `GET /health/live`, `GET /health/ready`, `GET /version`, and `GET /metrics`.
- Pydantic request and response contracts.
- Request ID, model version, latency, risk score, and decision in every successful prediction
  response; error/health contracts expose only fields appropriate to their schemas.
- Structured JSON logs without raw secrets or sensitive identifiers.
- AWS startup resolves the exact active SSM pointer once, downloads all seven S3 object VersionIds
  into an isolated bounded staging directory, verifies the immutable bundle and cross-artifact
  identity before deserialization, and atomically installs it on the empty ECS runtime volume.
  Hydration failure leaves predictions not ready and never falls back to stale or partial bytes.

### Prediction event pipeline
- Local MVP mode writes newline-delimited JSONL under `artifacts/predictions/`; Parquet is deferred.
- AWS mode sends events to Kinesis Data Firehose.
- Firehose batches GZIP JSONL with an explicit `.jsonl.gz` object suffix into UTC date/hour S3
  prefixes; model identity remains in the payload.
- Producer acceptance, Firehose delivery, and S3-prefix freshness are separate signals. A producer
  failure is observable and does not make prediction requests fail closed.

### Drift monitoring
- Reads the training baseline profile and a configurable recent window.
- Numeric drift using Population Stability Index (PSI), with optional KS statistic.
- Categorical drift using Jensen-Shannon distance (square root of base-2 divergence).
- Prediction score/decision distribution drift.
- Accepted-event missingness plus schema violations; under the strict v1 event contract a missing
  required feature is a schema rejection rather than a per-feature missingness attribution.
- Produces JSON and HTML reports.
- Separate states for monitor run, data quality, drift, and label-backed performance.
- UTC half-open event-time windows, a finalization grace, frozen input snapshots, event-ID
  deduplication, explicit target model identity, and exactly reconciled record counts.
- Grace delays finalization; the MVP does not claim row-level delivery-lateness measurement.
- Optional local delayed labels keyed by event ID. Without a configured label source performance is
  `unknown`; an inadequate configured source is `pending_labels`; adequate labels drive a versioned
  synthetic-cost policy and are described only as the labeled subset.
- Writes the latest status artifact and historical reports.
- Sends deduplicated SNS alerts after successful monitor runs for entry into data-quality `invalid`,
  drift `degraded`, or performance `degraded`; run failure/staleness is alarmed by CloudWatch.
- AWS scheduling invokes exactly one `aws-run` cycle. It snapshots one pointer and bounded S3 input
  set, persists immutable report/run evidence conditionally, emits one machine-readable result, and
  exits with a documented nonzero category for configuration, access, evidence, or sink failures.

### Dashboard
- Current status, model version, last report time, sample volume, and top drifting features.
- Prediction distribution and drift trend charts.
- Links to recent reports where available.
- Local mode reads local artifacts; AWS mode reads S3.
- AWS mode validates exact regional S3, CloudWatch metric, and CloudWatch Logs endpoints and renders
  source health as healthy, degraded, or unavailable without changing monitor-computed states.

### Cloud and delivery
- Terraform-managed AWS infrastructure.
- ECS Fargate for API and dashboard.
- Scheduled ECS task for drift monitoring.
- ALB for routing and health checks.
- ECR for images.
- S3 for model bundles, prediction events, reports, and separately bootstrapped Terraform state.
- CloudWatch logs and alarms.
- EventBridge Scheduler for periodic monitoring.
- SNS for optional email notification.
- GitHub Actions OIDC; no long-lived AWS access keys.
- CI quality gates and security scanning.
- Restricted ALB CIDR in every AWS mode. The preferred mode adds ACM HTTPS and a shared token;
  restricted HTTP is a short-lived synthetic-only fallback that must not transmit a reusable token.
- Private ECS tasks across two AZs with desired count one, one documented non-HA NAT, and an S3
  gateway endpoint; this is intentionally not a highly available service.
- Separate IAM responsibilities, exact OIDC claims, a retained manually created USD 10 monthly
  budget prerequisite, alarm matrix, lifecycle cleanup, guarded deployment/destroy, and durable
  rollback targets. Budget email entry occurs only in the AWS Console; it is never project input or
  evidence, and alerts are not a hard spending limit.
- Durable model identity includes semantic version plus manifest digest. Initial deployment is
  staged: create prerequisites with runtimes disabled, publish and verify images/model/pointer, then
  apply a second reviewed plan to activate services and the monitor schedule.
- Each deployable image is built and scanned once, then deployed by immutable digest without rebuild.
- Prometheus remains the local/test interface; AWS custom application signals reach CloudWatch via
  bounded-dimension Embedded Metric Format (EMF) logs, alongside native service metrics.
- Deployment governance has two explicit modes. `team_protected` requires a real independent
  reviewer and prevents self-review/admin bypass. `solo_portfolio` discloses the lack of separation
  of duties, requires a Public repository before Actions are enabled, and adds exact manual source,
  digest, plan-identity, confirmation, OIDC, lifetime, and destroy gates. Automated checks are not a
  substitute for independent review, and a documented upgrade returns to `team_protected`.
- A separate retained Terraform design records exact future state-object CloudTrail data events into
  private versioned KMS-encrypted storage with bounded retention and `prevent_destroy`; it is never
  owned by the disposable demo lifecycle.

## 5. Explicitly out of scope for MVP

- Kubernetes/EKS.
- Real payment data.
- Automatic retraining or automatic model promotion.
- Feature store.
- Online/AWS label collection and real-time model-performance metrics (local delayed labels only).
- Public anonymous access or permanent hosting.
- Multi-region failover.
- Full user authentication system.
- Bedrock/LLM incident summaries.
- Permanent production hosting.

## 6. Non-functional requirements

- Local-first: core behavior works without AWS credentials.
- Reproducible: fixed seeds and committed configuration.
- Testable: unit, contract, integration, and smoke tests.
- Secure by default: least privilege, no secrets in Git, non-root containers, dependency scanning.
- Observable: structured logs, health endpoints, Prometheus metrics, CloudWatch alarms.
- Cost-aware: demo environment is temporary and destroyable.
- Idempotent: scripts and Terraform should be safely repeatable.
- Explainable: design decisions and known limitations documented.

## 7. Success indicators

- A clean clone can run the local demo through documented commands.
- A prediction request returns a versioned result.
- A drift simulation changes status from healthy to degraded.
- The monitor creates machine-readable and human-readable reports.
- CI blocks a known test or lint failure.
- Terraform validation and security checks pass.
- AWS deployment can be destroyed without manual orphan cleanup.
- A 3–5 minute demo clearly communicates business value and engineering depth.
