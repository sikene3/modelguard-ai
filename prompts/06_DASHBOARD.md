# Phase 06 — Streamlit Operations Dashboard

## Recommended mode
GPT-5.6 Sol, Max.

## Objective
Create a polished, compact dashboard that communicates system health, model version, drift evidence, and data freshness without exaggerating conclusions.

## Required implementation
- Storage/repository interface for local artifacts and S3-ready implementation boundary.
- Separate cards for run, data-quality, drift, and label-backed performance states.
- Report timestamp/freshness, active model identity separately from report target identity,
  event/input-schema/baseline/config identities, window, accepted target volume, and exact
  rejected/outside-window/known-non-target/duplicate reconciliation.
- Top drifting features with metric, score, threshold, and severity.
- Numeric/categorical distribution comparisons where report data supports them.
- Prediction score/decision trend.
- Honest handling of missing, stale, insufficient, or malformed reports.
- `unknown`, `stale`, `insufficient_data`, and `pending_labels` must remain visually distinct; the UI
  must never infer performance from drift.
- Link/download behavior for HTML reports in local mode; safe link strategy for AWS mode.
- Responsive layout and readable labels.
- Unit tests for repository/parsing and smoke test for app startup.

## Constraints
- No authentication platform in MVP.
- No direct mutation/promotion controls from the dashboard.
- No fake real-time claims; display actual timestamps.
- Do not make dashboard logic own drift calculations.

## Validation

```bash
make dashboard
uv run pytest tests/unit tests/smoke -q
make verify
```

Capture local healthy and degraded screenshots for later use.
