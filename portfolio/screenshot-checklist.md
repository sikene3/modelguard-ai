# Screenshot and recording checklist

## Existing reviewed evidence

These four tracked PNGs already exist and contain synthetic/local evidence only. The Phase 11 pair
is visibly labeled as offline report-backed snapshots; the Phase 06 pair is a prior local
live-browser capture. None is presented as a currently live AWS console or endpoint.

- [x] [`../reports/evidence/phase-11/healthy-dashboard-evidence.png`](../reports/evidence/phase-11/healthy-dashboard-evidence.png) — 1440×1120, healthy, report-backed.
- [x] [`../reports/evidence/phase-11/degraded-dashboard-evidence.png`](../reports/evidence/phase-11/degraded-dashboard-evidence.png) — 1440×1120, degraded, report-backed.
- [x] [`../reports/evidence/phase-06/healthy-dashboard.png`](../reports/evidence/phase-06/healthy-dashboard.png) — 1440×1200, local browser capture.
- [x] [`../reports/evidence/phase-06/degraded-dashboard.png`](../reports/evidence/phase-06/degraded-dashboard.png) — 1440×1200, local browser capture.
- [x] [`assets/modelguard-architecture.png`](assets/modelguard-architecture.png) and
  [`assets/modelguard-architecture.svg`](assets/modelguard-architecture.svg) — exported from the
  tracked Mermaid source; diagrams, not screenshots.

Do not crop away the Phase 11 “offline report-backed” label. Do not relabel any of these images as a
live AWS capture.

## Manual capture set

- [x] **Prediction/readiness:** loopback URL only; show minimal readiness, version, and bounded
  prediction response. Hide shell prompt metadata and full request/event IDs if unnecessary.
- [x] **Healthy dashboard:** use the real local dashboard or the existing reviewed image; show all
  four states and accepted-event count.
- [x] **Degraded dashboard:** use the real local dashboard or the existing reviewed image; show
  changed drift state and retain `performance=unknown`.
- [x] **Incident report:** show state summary, report identity, breached signals, and synthetic
  boundary; omit local absolute paths.
- [ ] **CI/security evidence:** capture a current successful run summary only after checking job
  names and logs for private repository/account/runner data. Prefer test/check counts over raw logs.
- [x] **Short GIF:** real 15-second healthy → monitoring → degraded transition, saved as
  [`assets/demo/modelguard-drift.gif`](assets/demo/modelguard-drift.gif) after review.
- [x] **Demo video:** real 4-minute-15-second recording following
  [`demo-script.md`](demo-script.md), saved as
  [`assets/demo/modelguard-demo.mp4`](assets/demo/modelguard-demo.mp4).

## Privacy and truthfulness gate

Every new screenshot, GIF, or video must pass all items:

- [x] Synthetic data only; no real customer, payment, identity, or label data.
- [x] No AWS account ID, private endpoint, public IP, hostname, ARN, ECR registry, bucket/parameter
  name containing private context, or resource ID.
- [x] No email/notification address, GitHub secret/variable value, runner identity, browser profile,
  bookmarks, notification, or personal filesystem path.
- [x] No token, cookie, authorization header, QR/device code, `.env`, credentials/config file,
  Terraform state/plan, raw cloud response, command history, or environment dump.
- [x] The capture type is accurate: live browser, offline snapshot, diagram, local terminal, or
  historical evidence is labeled as such.
- [x] No unsupported text such as a real-world accuracy improvement, live permanent service,
  high-availability guarantee, zero downtime, automatic retraining, or real-time monitoring.
- [x] Performance is `unknown` unless an adequate, documented label source is visible and in scope.
- [x] The image is readable at the target platform size; filenames and alt text describe the state.
- [x] The final media hash/path/date and supporting report or command are added to
  [`claims-ledger.md`](claims-ledger.md).

## Reviewed media receipt

- MP4: `portfolio/assets/demo/modelguard-demo.mp4`; 255.036 seconds; 1280×720; H.264;
  SHA-256 `a8910b4c8fd9d392dc7e161cc773caefcff38501815f25f3e43d8f3fe6f07237`.
- GIF: `portfolio/assets/demo/modelguard-drift.gif`; 15.000 seconds; 960×540; animated;
  SHA-256 `e0a0f8112298ee633f8a9381859fa6d37554d110e67cbe9c53f189c40d1a1dc4`.
- Review date: 2026-08-11 UTC. The GIF's first live dashboard frame truthfully retains the
  event-time freshness state while its drift card changes from `healthy` to `degraded` and
  performance remains `unknown`.

## Recommended publish order

1. Architecture export.
2. Readiness/prediction frame.
3. Healthy dashboard.
4. Degraded dashboard.
5. Optional incident evidence or reviewed CI summary.

The current repository satisfies the four-image evidence count with the reviewed dashboard PNGs.
No additional static screenshot was needed: the genuine GIF and MP4 cover the remaining media
contract, while the optional CI/security still remains deliberately uncaptured.
