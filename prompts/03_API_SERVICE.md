# Phase 03 — FastAPI Inference Service

## Recommended mode
GPT-5.6 Sol, XHigh.

## Objective
Serve a verified model bundle through a typed, observable FastAPI service with clear liveness/readiness behavior.

## Required implementation
- Pydantic v2 prediction request/response schemas.
- `POST /v1/predict` with request ID, risk score, decision, model version, and latency.
- `GET /health/live`, `/health/ready`, `/version`, `/metrics`.
- Model loader validates bundle checksum, manifest, schema, and version.
- Startup/readiness behavior distinguishes process health from model readiness.
- Structured JSON logging with request correlation and no sensitive fields.
- Prometheus counters/histograms for requests, latency, decisions, model load, and errors.
- A dependency-injected telemetry boundary that can also emit tested low-cardinality EMF-compatible
  JSON to stdout in AWS mode; `/metrics` remains the local/test Prometheus surface. Never use request,
  event, token, feature, or arbitrary model-version values as CloudWatch metric dimensions.
- Configuration through typed settings and dependency injection.
- Bound request-body size, server concurrency, event-sink timeout, and graceful shutdown.
- Local access may be open. Every AWS ALB uses an explicit restricted CIDR. In `https_token` mode,
  `POST /v1/predict` requires a constant-time checked `Authorization: Bearer` token injected from a
  pre-created SSM SecureString ARN; query tokens are forbidden. In `http_cidr_only` fallback mode no
  reusable token is transmitted. Health routes are token-exempt and minimal for ALB checks;
  `/metrics` is not publicly routed. This is not a full auth platform.
- Unit, contract, and API integration tests.
- Concurrent-request, timeout, invalid/non-finite/extra-field, log-redaction, and measured local
  load tests with explicit throughput/error/latency targets.
- Example curl commands.

## Constraints
- Do not add AWS clients or event logging beyond a no-op interface stub if needed for architecture.
- Do not reload the model on every request.
- Do not expose stack traces or filesystem paths in production responses.
- Do not accept arbitrary extra fields silently unless explicitly documented.
- Do not log request bodies, auth headers, tokens, direct identifiers, or environment dumps.
- Do not claim authenticated or secure transport for the restricted HTTP fallback.

## Validation

```bash
make train
make api
curl -fsS http://127.0.0.1:8000/health/live
curl -fsS http://127.0.0.1:8000/health/ready
uv run pytest tests/unit tests/contract tests/integration -q
make verify
```

## Definition of done
A valid bundle yields a ready API and correct prediction contract; an invalid bundle fails readiness with tests proving the behavior.
