# Getting Started — ModelGuard AI Launch Kit

This repository began as an **execution plan, prompt set, and collection of quality gates**. Its
current status is documented in `README.md`: Phases 00–09 and the Phase 10 local code/runtime
readiness segment are implemented. The controlled live AWS deployment portion of Phase 10 remains
`in_progress`; no live AWS or GitHub evidence is implied by local tests.

## Correct starting point

```bash
cd modelguard-ai-launch-kit
chmod +x START_HERE.sh scripts/*.sh
./START_HERE.sh
make release-gates
```

`START_HERE.sh` performs the locked sync, local browser-login dependency check, and test gate. To
repeat only that network-free post-sync dependency proof, run
`uv run --frozen --no-sync python -m scripts.human_aws_login dependency`.

For a separately requested local container revalidation, `make docker-build`, `make scan-images`,
`make smoke-local`, `make demo-local`, and `make e2e-local` isolate each event/report run and write
only ignored evidence. They require no AWS credentials. See
`docs/CONTAINER_LOCAL_DEMO.md` for prerequisites, scenario details, image provenance, Trivy policy,
and troubleshooting. The earlier process-level `make api`, `make monitor`, `make dashboard`, and
`make load-test` paths remain useful for narrow development.

Reports for the completed local phases are under `reports/`; `reports/phase-10.md` is the current
evidence boundary. Do not start Phase 11. Continue only the unchecked live Phase 10 sequence after an
explicit approval for its next mutation. The first interactive authentication action, when approved,
is:

```bash
aws login --profile modelguard-bootstrap
```

That command is not part of `START_HERE.sh` and must not be run during a local-only review. After
login, the identity guard, retained prerequisites, saved plans, image publication, model publication,
activation, smoke, and teardown remain distinct review boundaries; follow
`docs/08_AWS_DEPLOYMENT_ORDER.md` exactly.

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
- Commit only when the current task explicitly authorizes it and every applicable gate passes; never
  amend or rewrite approved history.

The original launch-kit review and the rationale for its contract repairs are documented in
`docs/00_REVIEW_NOTES.md`.
