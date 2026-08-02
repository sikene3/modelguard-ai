# Getting Started — ModelGuard AI Launch Kit

This repository began as an **execution plan, prompt set, and collection of quality gates**. Its
current status is documented in `README.md`: repository bootstrap and the audited training workflow
plus the typed inference API are complete through Phase 03. Prediction-event persistence and later
phases have not been implemented.

## Correct starting point

```bash
cd modelguard-ai-launch-kit
chmod +x START_HERE.sh scripts/*.sh
./START_HERE.sh
make train
make verify
```

Then run `make api` in a dedicated terminal. From another terminal, verify `/health/live`,
`/health/ready`, and `/v1/predict` using the exact examples in `README.md`, then run `make load-test`.

Reports for Phases 00–03 are stored under `reports/`. Do not begin Phase 04 before reviewing the
current tree and commit. When it is time to begin Phase 04, use:

```bash
./scripts/run_phase.sh 04 xhigh
```

Read `RUN_ORDER.txt` and `prompts/README.md`. XHigh is the minimum reasoning level, Max is used for
statistical and cloud phases, and Ultra is reserved for the architecture and final audits. Phase 13
runs before Phase 12 so the final audit also reviews the portfolio content.

## Non-negotiable rules

- Do not advance until the current checklist, tests, evidence, and phase report are complete.
- Do not run AWS apply/destroy operations, change IAM, or push without direct human approval.
- Do not place keys, tokens, state, real data, or sensitive values in the repository, logs, or images.
- Drift is not accuracy. Measure performance only when enough valid labels exist.
- Do not claim that this project is "production-ready." The accurate description is a
  production-style synthetic demo.
- Commit only after a human review; agents must not commit automatically.

The original launch-kit review and the rationale for its contract repairs are documented in
`docs/00_REVIEW_NOTES.md`.
