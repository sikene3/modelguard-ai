#!/usr/bin/env python3
"""Create and verify immutable image release manifests from local and ECR evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Component = Literal["api", "dashboard", "monitor"]
COMPONENTS: tuple[Component, ...] = ("api", "dashboard", "monitor")
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ReleaseManifestError(RuntimeError):
    """A bounded release-evidence refusal reason."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImageRelease(StrictModel):
    component: Component
    repository: str
    provenance_tag: str = Field(pattern=r"^git-[0-9a-f]{40}$")
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    image_ref: str
    local_image_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_revision_label: str = Field(pattern=r"^[0-9a-f]{40}$")
    uv_lock_sha256_label: str = Field(pattern=r"^[0-9a-f]{64}$")
    dockerfile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_image: str
    cyclonedx_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    high_or_critical_findings: Literal[0]

    @model_validator(mode="after")
    def exact_reference(self) -> ImageRelease:
        if self.image_ref != f"{self.repository}@{self.digest}":
            raise ValueError("image_ref must be the exact repository digest")
        if "@sha256:" not in self.base_image:
            raise ValueError("release base image must be digest pinned")
        return self


class ImageReleaseManifest(StrictModel):
    schema_version: Literal["modelguard.image-release.v1"]
    source_commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    aws_account_id: str = Field(pattern=r"^[0-9]{12}$")
    aws_region: str = Field(pattern=r"^[a-z]{2}(-[a-z]+)+-[0-9]+$")
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    built_once: Literal[True]
    scanned_before_push: Literal[True]
    created_at: datetime
    images: dict[str, ImageRelease]

    @model_validator(mode="after")
    def exact_components(self) -> ImageReleaseManifest:
        if set(self.images) != set(COMPONENTS):
            raise ValueError("release manifest must contain exactly three components")
        if any(name != image.component for name, image in self.images.items()):
            raise ValueError("release image key/component mismatch")
        if any(image.source_revision_label != self.source_commit for image in self.images.values()):
            raise ValueError("release source labels must equal source_commit")
        if any(image.uv_lock_sha256_label != self.uv_lock_sha256 for image in self.images.values()):
            raise ValueError("release uv.lock labels must equal the manifest identity")
        if self.created_at.utcoffset() != timedelta(0):
            raise ValueError("created_at must be UTC")
        return self


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dockerfile_base(path: Path) -> str:
    dockerfile = path.read_text(encoding="utf-8")
    base_arguments = re.findall(
        r"^ARG PYTHON_BASE_IMAGE=([^\s]+)$",
        dockerfile,
        re.MULTILINE,
    )
    if (
        len(base_arguments) != 1
        or re.fullmatch(r"[^\s]+@sha256:[0-9a-f]{64}", base_arguments[0]) is None
    ):
        raise ReleaseManifestError("dockerfile_base_image_not_digest_pinned")
    base_image = str(base_arguments[0])
    from_images = re.findall(r"^FROM\s+([^\s]+)(?:\s+AS\s+[A-Za-z0-9_.-]+)?$", dockerfile, re.M)
    if not from_images or any(image != "${PYTHON_BASE_IMAGE}" for image in from_images):
        raise ReleaseManifestError("dockerfile_stage_bypasses_pinned_base")
    return base_image


def verify_release_source(repository_root: Path) -> None:
    """Reject any deployable Dockerfile stage that bypasses its digest-pinned base argument."""

    for component in COMPONENTS:
        _dockerfile_base(repository_root / "docker" / f"{component}.Dockerfile")


def _image_inspect(path: Path, *, component: str, expected_tag: str) -> dict[str, str]:
    payload = _load_json(path)
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        raise ReleaseManifestError("docker_inspect_shape_invalid")
    item = payload[0]
    image_id = item.get("Id")
    config = item.get("Config")
    repo_tags = item.get("RepoTags")
    repo_digests = item.get("RepoDigests")
    known_references = [
        reference
        for collection in (repo_tags, repo_digests)
        if isinstance(collection, list)
        for reference in collection
        if isinstance(reference, str)
    ]
    if (
        not isinstance(image_id, str)
        or SHA256_PATTERN.fullmatch(image_id) is None
        or not isinstance(config, dict)
        or config.get("User") != "10001:10001"
        or expected_tag not in known_references
    ):
        raise ReleaseManifestError("docker_inspect_identity_invalid")
    labels = config.get("Labels")
    if not isinstance(labels, dict):
        raise ReleaseManifestError("docker_inspect_labels_missing")
    source_revision = labels.get("org.opencontainers.image.revision")
    lock_sha = labels.get("io.modelguard.uv-lock.sha256")
    label_component = labels.get("io.modelguard.component")
    if (
        not isinstance(source_revision, str)
        or COMMIT_PATTERN.fullmatch(source_revision) is None
        or not isinstance(lock_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", lock_sha) is None
        or label_component != component
    ):
        raise ReleaseManifestError("docker_inspect_provenance_labels_invalid")
    return {"image_id": image_id, "source_revision": source_revision, "lock_sha": lock_sha}


def _ecr_identity(path: Path, *, expected_tag: str) -> str:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ReleaseManifestError("ecr_describe_root_invalid")
    details = payload.get("imageDetails")
    if not isinstance(details, list) or len(details) != 1 or not isinstance(details[0], dict):
        raise ReleaseManifestError("ecr_describe_image_count_invalid")
    detail = details[0]
    digest = detail.get("imageDigest")
    tags = detail.get("imageTags")
    if (
        not isinstance(digest, str)
        or SHA256_PATTERN.fullmatch(digest) is None
        or not isinstance(tags, list)
        or expected_tag not in tags
    ):
        raise ReleaseManifestError("ecr_describe_identity_invalid")
    return digest


def _cyclonedx_findings(path: Path) -> Literal[0]:
    payload = _load_json(path)
    if not isinstance(payload, dict) or payload.get("bomFormat") != "CycloneDX":
        raise ReleaseManifestError("trivy_cyclonedx_evidence_invalid")
    vulnerabilities = payload.get("vulnerabilities", [])
    if not isinstance(vulnerabilities, list):
        raise ReleaseManifestError("trivy_vulnerabilities_not_array")
    severe = 0
    for vulnerability in vulnerabilities:
        if not isinstance(vulnerability, dict):
            raise ReleaseManifestError("trivy_vulnerability_not_object")
        ratings = vulnerability.get("ratings", [])
        if not isinstance(ratings, list):
            raise ReleaseManifestError("trivy_ratings_not_array")
        severities = {
            rating.get("severity", "").casefold()
            for rating in ratings
            if isinstance(rating, dict) and isinstance(rating.get("severity"), str)
        }
        if severities & {"high", "critical"}:
            severe += 1
    if severe:
        raise ReleaseManifestError("release_contains_high_or_critical_findings")
    return 0


def create_manifest(
    *,
    repository_root: Path,
    evidence_dir: Path,
    account_id: str,
    region: str,
    source_commit: str,
    now: datetime | None = None,
) -> ImageReleaseManifest:
    """Bind one build/scan/push run to exact local IDs, ECR digests, and SBOM hashes."""

    if COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise ReleaseManifestError("source_commit_invalid")
    lock_sha = _sha256(repository_root / "uv.lock")
    registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    provenance_tag = f"git-{source_commit}"
    images: dict[str, ImageRelease] = {}
    for component in COMPONENTS:
        repository = f"{registry}/modelguard-ai/demo/{component}"
        tagged_ref = f"{repository}:{provenance_tag}"
        inspect = _image_inspect(
            evidence_dir / f"inspect-{component}.json",
            component=component,
            expected_tag=tagged_ref,
        )
        digest = _ecr_identity(evidence_dir / f"ecr-{component}.json", expected_tag=provenance_tag)
        cdx_path = evidence_dir / f"{component}.cdx.json"
        dockerfile = repository_root / "docker" / f"{component}.Dockerfile"
        images[component] = ImageRelease(
            component=component,
            repository=repository,
            provenance_tag=provenance_tag,
            digest=digest,
            image_ref=f"{repository}@{digest}",
            local_image_id=inspect["image_id"],
            source_revision_label=inspect["source_revision"],
            uv_lock_sha256_label=inspect["lock_sha"],
            dockerfile_sha256=_sha256(dockerfile),
            base_image=_dockerfile_base(dockerfile),
            cyclonedx_sha256=_sha256(cdx_path),
            high_or_critical_findings=_cyclonedx_findings(cdx_path),
        )
    manifest = ImageReleaseManifest(
        schema_version="modelguard.image-release.v1",
        source_commit=source_commit,
        aws_account_id=account_id,
        aws_region=region,
        uv_lock_sha256=lock_sha,
        built_once=True,
        scanned_before_push=True,
        created_at=now or datetime.now(tz=UTC),
        images=images,
    )
    if any(image.high_or_critical_findings for image in manifest.images.values()):
        raise ReleaseManifestError("release_contains_high_or_critical_findings")
    return manifest


def verify_manifest(
    manifest: ImageReleaseManifest,
    *,
    account_id: str,
    region: str,
    source_commit: str,
) -> None:
    """Refuse a manifest from another commit/account/Region or repository namespace."""

    expected = {
        "account_id": (manifest.aws_account_id, account_id),
        "region": (manifest.aws_region, region),
        "source_commit": (manifest.source_commit, source_commit),
    }
    mismatches = [name for name, (actual, wanted) in expected.items() if actual != wanted]
    if mismatches:
        raise ReleaseManifestError(f"release_identity_mismatch:{','.join(sorted(mismatches))}")
    prefix = f"{account_id}.dkr.ecr.{region}.amazonaws.com/modelguard-ai/demo/"
    for component, image in manifest.images.items():
        if (
            image.repository != f"{prefix}{component}"
            or image.provenance_tag != f"git-{source_commit}"
        ):
            raise ReleaseManifestError("release_repository_or_tag_mismatch")


def verify_live_evidence(manifest: ImageReleaseManifest, evidence_dir: Path) -> None:
    """Compare fresh ECR/inspect evidence with the already scanned release manifest."""

    for component, image in manifest.images.items():
        inspect = _image_inspect(
            evidence_dir / f"inspect-{component}.json",
            component=component,
            expected_tag=image.image_ref,
        )
        digest = _ecr_identity(
            evidence_dir / f"ecr-{component}.json", expected_tag=image.provenance_tag
        )
        if (
            digest != image.digest
            or inspect["image_id"] != image.local_image_id
            or inspect["source_revision"] != manifest.source_commit
            or inspect["lock_sha"] != manifest.uv_lock_sha256
        ):
            raise ReleaseManifestError("live_release_evidence_mismatch")


def _write_manifest(path: Path, manifest: ImageReleaseManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _append_github_output(path: Path, manifest: ImageReleaseManifest, manifest_path: Path) -> None:
    values = {f"{component}_ref": manifest.images[component].image_ref for component in COMPONENTS}
    values["manifest_sha256"] = _sha256(manifest_path)
    with path.open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            handle.write(f"{key}={value}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="release-manifest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--repository-root", type=Path, default=Path.cwd())
    create.add_argument("--evidence-dir", type=Path, required=True)
    create.add_argument("--account-id", required=True)
    create.add_argument("--region", required=True)
    create.add_argument("--source-commit", required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--github-output", type=Path)
    source = subparsers.add_parser("verify-source")
    source.add_argument("--repository-root", type=Path, default=Path.cwd())
    for command in ("verify", "verify-live"):
        item = subparsers.add_parser(command)
        item.add_argument("--manifest", type=Path, required=True)
        item.add_argument("--account-id", required=True)
        item.add_argument("--region", required=True)
        item.add_argument("--source-commit", required=True)
    subparsers.choices["verify-live"].add_argument("--evidence-dir", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "verify-source":
            verify_release_source(args.repository_root.resolve())
        elif args.command == "create":
            manifest = create_manifest(
                repository_root=args.repository_root.resolve(),
                evidence_dir=args.evidence_dir,
                account_id=args.account_id,
                region=args.region,
                source_commit=args.source_commit,
            )
            _write_manifest(args.output, manifest)
            if args.github_output is not None:
                _append_github_output(args.github_output, manifest, args.output)
        else:
            manifest = ImageReleaseManifest.model_validate(_load_json(args.manifest))
            verify_manifest(
                manifest,
                account_id=args.account_id,
                region=args.region,
                source_commit=args.source_commit,
            )
            if args.command == "verify-live":
                verify_live_evidence(manifest, args.evidence_dir)
        print(json.dumps({"status": "passed", "command": args.command}))
        return 0
    except (OSError, json.JSONDecodeError, ValidationError, ReleaseManifestError) as error:
        reason = str(error).splitlines()[0][:180]
        print(json.dumps({"status": "refused", "reason": reason}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
