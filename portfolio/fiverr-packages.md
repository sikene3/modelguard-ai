# Fiverr service packages

These are bounded implementation packages derived from the repository evidence. They describe
future client work, not a claim that an unknown client environment already satisfies the same
controls. Final scope depends on a short discovery review and written acceptance criteria.

## Tier 1 — Model API Foundation

**Typical duration:** 5 business days<br>
**Revisions:** 1 bounded revision round<br>
**Best for:** one existing, client-provided Python tabular model that needs a testable local service

### Included

- Package one supplied scikit-learn-compatible model behind one FastAPI prediction route.
- Add strict request/response schemas plus liveness, readiness, and version endpoints.
- Add structured error/logging boundaries without request-body or secret logging.
- Build one non-root Docker image and a local run configuration.
- Add focused unit/contract tests and a handoff README.

### Client provides

- A legally usable model artifact, representative non-sensitive schema/examples, Python dependency
  constraints, expected prediction behavior, and one technical contact.
- Written confirmation of trusted model provenance; untrusted pickle/joblib artifacts are rejected.

### Excluded

Model training or improvement, data cleaning, cloud infrastructure, CI/CD, monitoring, dashboards,
load/SLA certification, user authentication, compliance certification, and 24/7 support.

## Tier 2 — AWS Delivery Pipeline

**Typical duration:** 10 business days<br>
**Revisions:** 2 bounded revision rounds<br>
**Best for:** Tier 1 scope plus one temporary or staging AWS deployment in one Region

### Included

- Everything in Tier 1.
- Terraform for one ECS Fargate API service, ECR, ALB, private task networking, CloudWatch logs, and
  narrowly scoped runtime IAM.
- Restricted ingress; HTTPS requires the client's domain/certificate path and agreed secret source.
- GitHub Actions quality checks and OIDC-based AWS role assumption with no stored AWS access keys.
- Build once, scan, and deploy by immutable image digest.
- One reviewed deployment runbook, smoke check, and guarded teardown procedure.

### Client provides

- A client-owned AWS account, billing approval/budget alerts, GitHub repository and settings access,
  DNS/ACM prerequisites if HTTPS is required, approved CIDRs, and a qualified human approver.
- Timely access to deploy and remove the agreed staging resources.

### Excluded

Production on-call, multi-Region or HA design, Kubernetes, permanent hosting charges, penetration
testing, enterprise identity integration, database migration, data pipelines, drift monitoring,
automatic rollback guarantees, or compliance attestation.

## Tier 3 — MLOps Reliability Window

**Typical duration:** 15 business days<br>
**Revisions:** 2 bounded revision rounds<br>
**Best for:** one tabular model that needs auditable prediction events and scheduled drift evidence

### Included

- Everything in Tier 2.
- One versioned prediction-event contract and one Firehose/S3 or equivalent bounded batch sink.
- One training-reference baseline supplied or generated from approved reference data.
- Scheduled numeric/categorical and prediction-distribution drift over one agreed finalized window.
- JSON/HTML incident reports, independent run/data-quality/drift/performance states, one read-only
  status dashboard, and one bounded alert transition.
- One healthy-to-shifted synthetic acceptance scenario, failure runbook, architecture handoff, and
  claim/evidence summary.

### Client provides

- Approved reference data with schema and retention rules, expected event volume/window, monitoring
  thresholds or approval to use a clearly labeled initial heuristic, and notification ownership.
- Labels joined by stable event ID if label-backed performance is required. Without adequate labels,
  performance is reported as `unknown` or `pending_labels`.

### Excluded

Automatic retraining/promotion, proof that drift caused a performance change, real-time per-event
monitoring, streaming platforms such as Kafka, feature stores, LLM incident summaries, bespoke BI,
24/7 operations, model-risk validation, fairness certification, legal/compliance advice, data
labeling, and guaranteed business outcomes.

## Exclusions common to every tier

- Real payment/cardholder data, secrets sent through chat, or long-lived cloud access keys.
- Work outside the agreed repository/account/Region/model and written acceptance criteria.
- Third-party fees, cloud charges, domains, certificates, paid runners, or marketplace products.
- Claims of production readiness, guaranteed uptime, zero vulnerabilities, zero cost, or model
  accuracy/business improvement without separately agreed evidence.
- Destructive migration or teardown outside the explicitly named demo/staging resources.

Anything outside a tier becomes a separate milestone after written scope, evidence, cost, and access
review.
