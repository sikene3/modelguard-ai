# Phase 09 Checklist

- [x] CI workflow
- [x] Container scan workflow
- [x] Terraform plan workflow
- [x] Image publish workflow
- [x] Protected deploy workflow
- [x] OIDC only
- [x] Immutable tags
- [x] Actions/base images pinned; build once and promote exact digest
- [x] Each image is built/scanned once and deployed as `repository@sha256`
- [x] Protected environment and deployment concurrency
- [x] Durable last-known-good task/model rollback targets
- [x] Post-deploy smoke
- [x] No PR auto-apply
- [x] Customized legacy/immutable OIDC subjects bind exact repository, ref, environment, workflow,
      and audience; untrusted jobs have no id-token/AWS/state access
- [x] Pinned history secret scan with redacted output and expiring scoped allowlist
- [x] Raw plan restricted to same-identity transfer; redacted summary is public evidence
- [x] Notification PII is absent from Terraform/state/saved-plan artifacts; the budget carries only
      its non-secret SNS ARN and protected human/SSO email enrollment is verified value-free before
      image publication
- [x] Budget and CloudWatch KMS key-policy statements independently require exact account, source
      ARN, topic encryption context, and regional SNS `kms:ViaService` conditions
- [x] Mutations of the actual Terraform statements reject wrong SourceAccount, Budget/CloudWatch
      SourceArn, SNS encryption context, ViaService service/Region, missing conditions, and a
      workload-IAM-only ViaService
- [x] HTTPS smoke supplies the validated bearer token only through anonymous curl-config stdin;
      fake-curl regression tests prove it is absent from argv, child environment, output, and files
- [x] Repository-wide manifest scanning rejects bearer-token expansion from documentation and curl
      arguments; only the two hardened parent-shell reads remain
- [x] Protected prerequisite and activation plans enforce the startup barrier

## Evidence

- Commands: See `reports/phase-09.md` for the original closure and `reports/phase-09-1.md` for the
  superseding reproducible scanner gate and exact local results.
- Test results: 255 passed; 84.72% branch coverage. Phase 09 focus: 39 passed; combined Phase 08/09
  security contracts: 56 passed; the targeted KMS/bearer selection passed all 23 cases; strict hashed
  pip-audit found no known vulnerabilities after the audited dependency repair.
- Artifact paths: Workflow-only ignored paths under `artifacts/ci/`,
  `artifacts/container-security/`, `artifacts/image-release/`, and `artifacts/deploy/`; repository
  evidence is recorded in `reports/phase-09.md`, `reports/phase-09-1.md`,
  `checklists/PHASE_09_1.md`, `tasks/phase_status.json`, and `FILE_MANIFEST.txt`.
- Commit: Controlled by the final independent closure gate; its hash is reported separately because
  a commit cannot contain its own identity.
- Residual risks: No GitHub/OIDC/AWS workflow has executed. Phase 09.1 ran actionlint, yamllint,
  ShellCheck, Checkov, Gitleaks, and Trivy locally through the pinned repository toolchain; live
  GitHub expression/SARIF/OIDC/artifact behavior and provider-backed Terraform validation remain
  mandatory release-runner gates. Phase 10 runtime activation remains fail-closed until API bundle
  hydration, dashboard AWS config, and monitor `aws-run` exist.
