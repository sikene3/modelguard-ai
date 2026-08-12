# AWS runtime contracts

This document defines the code-only Phase 10 runtime boundary. It does not claim that an AWS task,
GitHub workflow, image publication, or Terraform apply has run. Runtime code uses the ECS task role
through the default AWS SDK credential provider; no profile or static credential is accepted by an
application entry point.

## Create-only model publication and promotion

`python -m scripts.model_bundle_publisher publish-and-promote` is the only supported model
publication command. Its local validation calls the existing strict bundle inspector and compressed
model bound before constructing AWS clients. The cloud mutation path then:

1. requires the exact account-derived model bucket in `us-east-1`, explicit bucket-location response,
   and enabled S3 versioning;
2. acquires `model-bundles/.modelguard-promotion.lock` with `If-None-Match: *`, SSE-S3, a SHA-256
   request checksum, and an owner check, then reads the exact lock VersionId back before proceeding;
3. lists version history—not only current keys—for `model-bundles/<semantic-version>/` and refuses
   any object version or delete marker, so a deleted or partial prior attempt cannot be reused;
4. conditionally creates six payloads and then `checksums.sha256`, requires SSE-S3, SDK checksum and
   nonempty S3 VersionId responses, and reads each exact VersionId back under its measured bound to
   compare metadata, checksum, content type, length, and bytes;
5. snapshots and strictly parses both non-secret SSM String pointers, rechecks their versions and
   bytes under the lock, copies the old active value to previous, and writes the new active pointer
   last; every write is read back at the returned SSM parameter version;
6. restores the original active and previous values after any attempted promotion failure. If either
   rollback cannot be verified, the command retains the lock and refuses all later publication until
   an explicitly reviewed repair proves both pointers. Otherwise it deletes only its exact lock
   VersionId and verifies that no live lock is exposed.

Model objects are never deleted or overwritten by this command. A failed partial upload is inactive
but permanently consumes that semantic version; recovery requires investigating it and publishing a
new reviewed semantic version. Pointer visibility is the commit boundary, so incomplete object sets
are never activated. The S3 lock serializes compliant publishers; the restricted deploy trust
boundary prevents bypass writes.

The CLI accepts only bundle path, non-secret expected account/Region/identity selectors, and an exact
non-secret confirmation phrase. It accepts no access key, session token, bearer token, password,
generic endpoint, or output-file argument. Success prints only model/manifest/pointer identities,
seven VersionIds, fixed parameter names, and status. Refusals print only bounded reason categories.
It has not been run against AWS in the local readiness segment.

## API bundle hydration

An AWS API task starts with an empty model destination on its task-scoped writable `/runtime`
volume. The API and monitor images declare that exact image-owned path with `VOLUME`, so Amazon ECS
copies its UID/GID 10001 ownership and mode into the matching Fargate bind mount instead of creating
a root-owned default mount.
Startup performs this ordered,
fail-closed sequence:

1. Call `GetBucketLocation` for the exact configured model bucket. Require an explicit
   `LocationConstraint` field, map only an explicit null value to `us-east-1`, and reject a missing,
   denied, malformed, or cross-Region response before any object read.
2. Read `/modelguard-ai/demo/models/active` once without decryption, parse it with duplicate-key
   rejection, and validate the strict
   `modelguard.active-monitor-target.v1` pointer.
3. Require the configured model bucket, semantic version, exact
   `model-bundles/<version>/` prefix, target identity, seven approved filenames, and seven nonempty
   S3 VersionIds to agree before any object read.
4. Create a mode-0700 staging directory on the destination filesystem. Fetch each exact object by
   bucket, key, and VersionId; require the response VersionId and bounded `ContentLength` to match;
   write each file create-only as mode 0600 and `fsync` it.
5. Inspect the complete bundle without deserializing it. Reject extra/missing files, unsafe paths,
   malformed schemas, size violations, checksum changes, version or manifest substitution, and any
   cross-artifact identity mismatch. The measured per-file ceilings bound the complete compressed
   seven-object download below 1.25 MiB; `model.joblib` is bounded to 64 KiB compressed and its
   reviewed zlib stream to 4 MiB inflated bytes before trusted deserialization. These measured
   ceilings replace the former generic 256 MiB allowance for the 1 GiB API task.
6. Rename the verified directory atomically into `/runtime/model-bundle`, `fsync` the parent, repeat
   the trusted-bundle verification, and only then deserialize and install the model once.

An existing destination is never reused merely because its semantic model identity looks valid: it
lacks proof of the current pointer's exact bucket, prefix, keys, and VersionIds, so startup refuses
it. An interruption, S3/SSM error, collision, corrupt object, mixed version, or failed verification
removes staging bytes. The API keeps liveness available where possible, reports not-ready, and
refuses predictions. It never serves a partial bundle or silently falls back to another model.

## Dashboard AWS evidence-source health

The dashboard continues to read only validated Phase 05 reports; it never recomputes drift or
performance. AWS mode additionally requires an exact typed health contract:

- `AWS_REGION=us-east-1` and an identical `DASHBOARD_SOURCE_REGION`;
- exact model/report buckets and dashboard identifier;
- `ModelGuardAI / MonitorCompletions` with fixed `Service=monitor` and `Environment=aws`
  dimensions;
- exact `/modelguard-ai/demo/monitor` log group;
- exact regional HTTPS endpoints for S3, CloudWatch metrics, and CloudWatch Logs.

The probe checks both bucket Regions, metric identity availability, and monitor log-stream metadata
with bounded SDK timeouts. Each source is independently `healthy`, `missing_data`,
`permission_denied`, `wrong_region`, `malformed_response`, or `unavailable`. Only four healthy
sources produce healthy source status. A partial failure is degraded; total inaccessible evidence is
unavailable. This source status is displayed separately and never changes run, data-quality, drift,
or performance states persisted by monitoring.

## One-shot monitor `aws-run`

`python -m modelguard.monitoring.cli aws-run` executes exactly one cycle and exits. It does not loop,
daemonize, fit, select a threshold, mutate a model, or infer performance from drift. The command:

1. validates monitor-specific AWS configuration, three distinct buckets, exact SSM parameter,
   exact regional SNS topic, absolute runtime path, and the one canonical in-image monitoring
   policy. Its canonical semantic SHA-256 is
   `edd3177bc4a692262858b6ec2e60a991cdce1bc844ef7eb0becac6846df56c73`; `aws-run`
   accepts no policy-path override;
2. snapshots the target once, hydrates the exact bundle, and enumerates only Firehose's explicit
   `.jsonl.gz` contract under the finite UTC arrival-hour prefixes overlapping the event window and
   finalization grace. Enumeration shares one global page/entry/object/byte budget across prefixes,
   deduplicates object keys, rejects malformed/truncated/token-cycling pages and out-of-prefix keys,
   and pins every accepted object by VersionId or ETag before bounded reads/decompression;
3. evaluates the existing deterministic UTC half-open-window contract with performance `unknown`
   because online AWS labels are out of scope;
4. publishes immutable JSON/HTML history, updates `latest.json` only for a newer window, claims
   transition markers conditionally, writes run status without losing prior success, and sends any
   transition through the exact SNS boundary;
5. writes bounded low-cardinality EMF to stderr and exactly one canonical v1 JSON result to stdout.

Exit codes are stable:

| Code | Meaning |
|---:|---|
| `0` | Complete valid cycle and persisted evidence |
| `2` | Missing, malformed, or contradictory configuration |
| `3` | AWS credential/provider/authorization operation failed |
| `4` | Corrupt, invalid, or insufficient monitoring evidence |
| `5` | Report, alert, telemetry, or run-status persistence failed |

Identical finalized inputs produce the same report ID and bytes; a rerun does not rewrite immutable
history or advance an identical latest pointer. Missing data, permission denial, corrupt model
evidence, Region mismatch, SNS failure, and S3 failure return nonzero.

## Image and activation evidence

`scripts/verify_release_runtime.sh` accepts either three immutable registry digest references or,
only under the explicit local mode, three exact Docker image IDs. It verifies numeric non-root image
users and runs each in a networkless, read-only, capability-free container with
`no-new-privileges`. The probes inspect the installed application and exercise the three negative
contracts above.

Before every run, the verifier invalidates only the exact caller-selected prior regular output. A
failure cannot leave stale success evidence. On complete success it writes a mode-0600 temporary
record, `fsync`s it, and atomically renames it into place.

The emitted `modelguard.runtime-contract-verification.v2` binds the exact source commit, image
revision label, image identities, mode, three contract results, and SHA-256 of `uv.lock`. The same
lock identity is required in each image label and the immutable release manifest. A local dirty-tree
build is explicitly labeled `<HEAD>-dirty` and can produce only local-image-ID evidence; an
activation-capable record requires `source_revision` to equal the exact clean source commit.
`scripts/render_ci_terraform.py` refuses
activation when that record is absent, malformed, local-image-only, or different from the three
activation image references. The committed Terraform default remains
`runtime_contract_verified=false`; only a matching digest-mode record can render it true for an
ephemeral activation input. Live ECS readiness remains a separate deployment acceptance gate.

The verifier also performs a fail-closed Docker host-capability preflight. If the local daemon
cannot execute even `/bin/true` with `no-new-privileges`, it returns nonzero and emits no record;
running application probes after removing that control is diagnostic only and cannot satisfy the
sealed image gate.

The dashboard build excludes Streamlit's optional GitPython, gitdb, and smmap chain because file
watching and repository integration are disabled in the release command. The full development lock
still retains MLflow's GitPython requirement at the patched `>=3.1.58` floor. Tests prove the
dashboard starts without the optional modules, and exact-image Trivy scanning remains blocking.
