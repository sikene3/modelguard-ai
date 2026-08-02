# Getting Started — ModelGuard AI Launch Kit

This repository began as an **execution plan, prompt set, and collection of quality gates**. Its
current status is documented in `README.md`: repository bootstrap, audited training, the typed
inference API, versioned prediction-event logging, deterministic drift/data-quality/delayed-label
monitoring, the read-only operations dashboard, and the verified local container workflow are
complete through Phase 07. Later AWS infrastructure and delivery phases are not implemented.

## Correct starting point

```bash
cd modelguard-ai-launch-kit
chmod +x START_HERE.sh scripts/*.sh
./START_HERE.sh
make train
./scripts/build_local_images.sh
docker compose up -d
./scripts/smoke_local.sh
./scripts/demo_local.sh
./scripts/e2e_local.sh
./scripts/scan_local_images.sh
docker compose down -v
make verify
```

The container scripts automatically isolate each event/report run, close API event files cleanly,
validate every expected state, and write machine-readable evidence under ignored
`artifacts/phase-07-evidence/` paths. They require no AWS credentials. See
`docs/CONTAINER_LOCAL_DEMO.md` for prerequisites, scenario details, image provenance, Trivy policy,
and troubleshooting. The earlier process-level `make api`, `make monitor`, `make dashboard`, and
`make load-test` paths remain useful for narrow development.

Reports for Phases 00–07 are stored under `reports/`; `reports/phase-07.md` records the completed
runtime and security gates. Do not begin Phase 08 until the current Phase 07 tree receives an
independent human review and is manually committed. After that gate, use:

```bash
./scripts/run_phase.sh 08 max
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
