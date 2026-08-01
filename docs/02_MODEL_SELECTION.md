# Selecting the Reasoning Level

| Phase | Level | Rationale |
| --- | --- | --- |
| 00 | Ultra | Independent architecture, ML, AWS, and delivery review |
| 01–04 | XHigh | Foundation and bounded core contracts that still require careful review |
| 05 | Max | Statistics, edge cases, delayed labels, and idempotency |
| 06 | Max | State semantics and UX without misleading claims |
| 07 | XHigh | Containers and local end-to-end behavior within clear boundaries |
| 08–11 | Max | High-risk IAM, networking, state, CI, deployment, and failure interactions |
| 13 | XHigh | Evidence-bounded commercial content before the final audit |
| 12 | Ultra | Independent final audit of code and claims |

High and Medium are not used in this plan. XHigh is the minimum, Max is for highly coupled phases or
work where errors are costly, and Ultra is for multi-workstream reviews rather than building the
entire project at once.

Run a phase with:

```bash
./scripts/run_phase.sh 03 xhigh
./scripts/run_phase.sh 08 max
```

Select Ultra interactively through `/model`. Every reasoning level still requires a precise prompt,
tests, evidence, and human review. Higher reasoning effort does not authorize AWS changes, commits,
pushes, or destructive operations.
