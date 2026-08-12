# LinkedIn post

## Copy-ready post

I built ModelGuard AI to stop two quiet ML failures: loading the wrong model artifacts and calling
distribution drift an accuracy problem before labels exist.

The project starts with deterministic synthetic fraud data and ends with a versioned prediction
service, lineage-preserving events, finalized drift windows, immutable incident reports, and a
read-only dashboard. The important part is the behavior when something goes wrong:

- incomplete or inconsistent model bundles never become ready;
- a 50-event window becomes `insufficient_data`, not “healthy”;
- a controlled event-sink outage remains visible while a valid prediction still returns;
- a shifted 1,000-event window moves drift from `healthy` to `degraded`;
- performance stays `unknown` because the demo has no labels—so I make no accuracy-loss claim.

For AWS, I used a restricted, temporary ECS Fargate environment with S3, Firehose, EventBridge
Scheduler, CloudWatch, SNS, ECR, SSM, Terraform, and GitHub Actions OIDC. Images were built/scanned
once and activated by digest after a separate prerequisite plan. I captured the evidence and then
destroyed the disposable environment; the design intentionally keeps one NAT Gateway and one task
per service, so it is not highly available.

What I learned: a useful MLOps portfolio project is not the longest technology list. It is a set of
explicit identities, failure states, review boundaries, and evidence that prevents a green
dashboard from hiding an unknown condition.

All data is synthetic, the cloud environment was temporary, and automatic retraining is
deliberately out of scope. The repository includes the architecture, local quickstart, case study,
failure-demo evidence, security gates, cost/teardown notes, and a claim-by-claim evidence ledger.

#AWS #MLOps #DevOps #DataEngineering #MachineLearning

## Suggested media order

1. [`assets/modelguard-architecture.png`](assets/modelguard-architecture.png) — architecture.
2. [`../reports/evidence/phase-11/healthy-dashboard-evidence.png`](../reports/evidence/phase-11/healthy-dashboard-evidence.png) — stationary window.
3. [`../reports/evidence/phase-11/degraded-dashboard-evidence.png`](../reports/evidence/phase-11/degraded-dashboard-evidence.png) — shifted window.
4. [`assets/demo/modelguard-drift.gif`](assets/demo/modelguard-drift.gif) — genuine current-run
   healthy-to-degraded transition; the full recording is
   [`assets/demo/modelguard-demo.mp4`](assets/demo/modelguard-demo.mp4).

All four suggested assets are repository-backed and reviewed. Preserve the synthetic/local labels
and do not upload any alternate frame containing a private endpoint, account identifier, token,
email address, ARN, or raw cloud receipt.
