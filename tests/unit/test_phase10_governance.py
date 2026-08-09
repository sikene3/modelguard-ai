"""Dual deployment-governance and immutable evidence contract tests."""

from __future__ import annotations

import base64
import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from scripts.deployment_governance import (
    EntryContract,
    GovernanceRefusal,
    verify_entry,
    verify_release_evidence,
)


def _entry(mode: str = "team_protected", operation: str = "deploy") -> EntryContract:
    paths = {
        "plan": ("demo-plan", ".github/workflows/terraform-plan.yml", "push", None),
        "publish": (
            "demo",
            ".github/workflows/publish-images.yml",
            "workflow_dispatch",
            "PUBLISH modelguard-ai images",
        ),
        "deploy": (
            "demo",
            ".github/workflows/deploy-demo.yml",
            "workflow_dispatch",
            "DEPLOY modelguard-ai demo",
        ),
        "activation": (
            "demo",
            ".github/workflows/deploy-demo.yml",
            "workflow_dispatch",
            "DEPLOY modelguard-ai demo",
        ),
        "rollback": (
            "demo",
            ".github/workflows/rollback-demo.yml",
            "workflow_dispatch",
            (
                "ROLLBACK SOLO modelguard-ai demo"
                if mode == "solo_portfolio"
                else "ROLLBACK TEAM modelguard-ai demo"
            ),
        ),
        "destroy": (
            "demo-destroy",
            ".github/workflows/destroy-demo.yml",
            "workflow_dispatch",
            (
                "DESTROY SOLO modelguard-ai demo"
                if mode == "solo_portfolio"
                else "DESTROY TEAM modelguard-ai demo"
            ),
        ),
    }
    environment, path, event_name, confirmation = paths[operation]
    if mode == "solo_portfolio":
        event_name = "workflow_dispatch"
    return EntryContract(  # type: ignore[arg-type]
        mode=mode,
        operation=operation,
        repository="sikene3/modelguard-ai",
        repository_visibility="public" if mode == "solo_portfolio" else "private",
        event_name=event_name,
        git_ref="refs/heads/main",
        environment=environment,
        workflow_ref=f"sikene3/modelguard-ai/{path}@refs/heads/main",
        job_workflow_ref=f"sikene3/modelguard-ai/{path}@refs/heads/main",
        source_commit="a" * 40,
        workflow_commit="a" * 40,
        job_workflow_commit="a" * 40,
        confirmation=confirmation,
    )


@pytest.mark.parametrize("mode", ["team_protected", "solo_portfolio"])
@pytest.mark.parametrize(
    "operation",
    ["plan", "publish", "deploy", "activation", "rollback", "destroy"],
)
def test_both_governance_modes_keep_exact_repository_ref_environment_and_workflow(
    mode: str,
    operation: str,
) -> None:
    assert verify_entry(_entry(mode, operation))["status"] == "passed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("repository", "attacker/modelguard-ai"),
        ("repository_visibility", "public"),
        ("event_name", "pull_request"),
        ("git_ref", "refs/heads/feature"),
        ("environment", "demo-plan"),
        (
            "workflow_ref",
            "sikene3/modelguard-ai/.github/workflows/attacker.yml@refs/heads/main",
        ),
        ("source_commit", "b" * 40),
        ("confirmation", "DEPLOY something else"),
    ],
)
def test_team_deployment_rejects_every_altered_trust_or_evidence_input(
    field: str,
    value: str,
) -> None:
    with pytest.raises(GovernanceRefusal):
        verify_entry(replace(_entry(), **{field: value}))


def test_solo_mode_requires_public_repository_and_manual_mutation_dispatch() -> None:
    solo = _entry("solo_portfolio", "deploy")
    with pytest.raises(GovernanceRefusal, match="repository_visibility"):
        verify_entry(replace(solo, repository_visibility="private"))
    with pytest.raises(GovernanceRefusal, match="not_manual"):
        verify_entry(replace(solo, event_name="push"))
    with pytest.raises(GovernanceRefusal, match="not_manual"):
        verify_entry(replace(_entry("solo_portfolio", "publish"), event_name="workflow_call"))


def test_publish_entry_distinguishes_direct_dispatch_from_reusable_caller_identity() -> None:
    direct = _entry("team_protected", "publish")
    assert verify_entry(direct)["status"] == "passed"

    reusable = replace(
        direct,
        event_name="workflow_call",
        workflow_ref=("sikene3/modelguard-ai/.github/workflows/deploy-demo.yml@refs/heads/main"),
    )
    assert verify_entry(reusable)["status"] == "passed"
    with pytest.raises(GovernanceRefusal, match="workflow_identity"):
        verify_entry(replace(reusable, workflow_ref=direct.workflow_ref))
    with pytest.raises(GovernanceRefusal, match="job_workflow_identity"):
        verify_entry(replace(reusable, job_workflow_ref=reusable.workflow_ref))
    with pytest.raises(GovernanceRefusal, match="source_commit"):
        verify_entry(replace(reusable, job_workflow_commit="b" * 40))


def test_workflows_use_actual_caller_and_job_workflow_identities(repository_root: Path) -> None:
    for workflow_name in (
        "deploy-demo.yml",
        "destroy-demo.yml",
        "publish-images.yml",
        "rollback-demo.yml",
        "terraform-plan.yml",
    ):
        source = (repository_root / ".github/workflows" / workflow_name).read_text()
        assert "WORKFLOW_REF: ${{ github.workflow_ref }}" in source
        assert "JOB_CONTEXT: ${{ toJSON(job) }}" in source
        assert ".workflow_ref" in source
        assert ".workflow_sha" in source
        assert '--job-workflow-ref "$job_workflow_ref"' in source
        assert '--job-workflow-commit "$job_workflow_commit"' in source
        assert "JOB_WORKFLOW_REF: ${{ github.repository }}/.github/workflows/" not in source


def test_governance_rejects_unknown_mode_and_operation_at_the_python_boundary() -> None:
    with pytest.raises(GovernanceRefusal, match="mode_invalid"):
        verify_entry(replace(_entry(), mode="unknown"))  # type: ignore[arg-type]
    with pytest.raises(GovernanceRefusal, match="operation_invalid"):
        verify_entry(replace(_entry(), operation="unknown"))  # type: ignore[arg-type]


def test_release_evidence_binds_exact_three_digests_plan_hash_and_identity() -> None:
    account = "123456789012"
    refs = tuple(
        f"{account}.dkr.ecr.us-east-1.amazonaws.com/modelguard-ai/demo/"
        f"{component}@sha256:{digest * 64}"
        for component, digest in (("api", "1"), ("dashboard", "2"), ("monitor", "3"))
    )
    arguments = {
        "governance_mode": "solo_portfolio",
        "stage": "activation",
        "run_identity": "123:1:activation",
        "reviewed_run_identity": "123:1:activation",
        "confirmation": "ACTIVATE SOLO modelguard-ai demo",
        "source_commit": "a" * 40,
        "workflow_commit": "a" * 40,
        "image_refs": refs,
        "reviewed_image_refs": refs,
        "model_pointer_sha256": "d" * 64,
        "reviewed_model_pointer_sha256": "d" * 64,
        "plan_sha256": "b" * 64,
        "reviewed_plan_sha256": "b" * 64,
        "plan_identity_sha256": "c" * 64,
        "reviewed_plan_identity_sha256": "c" * 64,
    }
    assert verify_release_evidence(**arguments) == {  # type: ignore[arg-type]
        "governance_mode": "solo_portfolio",
        "run_identity": "123:1:activation",
        "stage": "activation",
        "status": "passed",
    }
    for field, value in (
        ("source_commit", "d" * 40),
        ("image_refs", (refs[0], refs[1], refs[1])),
        ("reviewed_plan_sha256", "e" * 64),
        ("reviewed_plan_identity_sha256", "f" * 64),
        ("model_pointer_sha256", "0" * 63),
        ("run_identity", "123:1:prerequisites"),
        ("reviewed_run_identity", "124:1:activation"),
        ("reviewed_image_refs", (refs[0], refs[1], refs[1])),
        ("reviewed_model_pointer_sha256", "e" * 64),
        ("confirmation", "ACTIVATE TEAM modelguard-ai demo"),
    ):
        with pytest.raises(GovernanceRefusal):
            verify_release_evidence(**{**arguments, field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize("mode", ["team_protected", "solo_portfolio"])
@pytest.mark.parametrize("stage", ["prerequisites", "destroy"])
def test_non_activation_plan_review_binds_mode_run_hashes_and_exact_phrase(
    mode: str,
    stage: str,
) -> None:
    confirmation = (
        f"APPLY {'TEAM' if mode == 'team_protected' else 'SOLO'} modelguard-ai prerequisites"
        if stage == "prerequisites"
        else f"DESTROY {'TEAM' if mode == 'team_protected' else 'SOLO'} modelguard-ai demo"
    )
    result = verify_release_evidence(
        governance_mode=mode,  # type: ignore[arg-type]
        stage=stage,  # type: ignore[arg-type]
        run_identity=f"123:2:{stage}",
        reviewed_run_identity=f"123:2:{stage}",
        confirmation=confirmation,
        source_commit="a" * 40,
        workflow_commit="a" * 40,
        image_refs=None,
        reviewed_image_refs=None,
        model_pointer_sha256=None,
        reviewed_model_pointer_sha256=None,
        plan_sha256="b" * 64,
        reviewed_plan_sha256="b" * 64,
        plan_identity_sha256="c" * 64,
        reviewed_plan_identity_sha256="c" * 64,
    )
    assert result["status"] == "passed"
    with pytest.raises(GovernanceRefusal, match="confirmation"):
        verify_release_evidence(
            governance_mode=mode,  # type: ignore[arg-type]
            stage=stage,  # type: ignore[arg-type]
            run_identity=f"123:2:{stage}",
            reviewed_run_identity=f"123:2:{stage}",
            confirmation="wrong",
            source_commit="a" * 40,
            workflow_commit="a" * 40,
            image_refs=None,
            reviewed_image_refs=None,
            model_pointer_sha256=None,
            reviewed_model_pointer_sha256=None,
            plan_sha256="b" * 64,
            reviewed_plan_sha256="b" * 64,
            plan_identity_sha256="c" * 64,
            reviewed_plan_identity_sha256="c" * 64,
        )


def test_workflows_and_terraform_expose_mode_without_weakening_exact_oidc_trust(
    repository_root: Path,
) -> None:
    deploy = (repository_root / ".github/workflows/deploy-demo.yml").read_text()
    publish = (repository_root / ".github/workflows/publish-images.yml").read_text()
    plan = (repository_root / ".github/workflows/terraform-plan.yml").read_text()
    variables = (repository_root / "infrastructure/bootstrap/variables.tf").read_text()
    iam = (repository_root / "infrastructure/bootstrap/iam.tf").read_text()
    outputs = (repository_root / "infrastructure/bootstrap/outputs.tf").read_text()

    assert all("DEPLOYMENT_GOVERNANCE_MODE" in source for source in (deploy, publish, plan))
    assert "team_protected" in variables and "solo_portfolio" in variables
    assert 'test     = "StringEquals"' in iam
    assert "values   = [local.plan_subject]" in iam
    assert "values   = values(local.deploy_subjects)" in iam
    assert "rollback = local.deploy_subjects.rollback" in outputs
    assert 'environment",\n    var.github_plan_environment' in iam
    assert 'environment",\n      var.github_deploy_environment' in iam
    plan_trust = iam.split('data "aws_iam_policy_document" "github_plan_trust"', 1)[1]
    assert "StringLike" not in plan_trust.split("resource", 1)[0]


def test_public_workflows_never_upload_raw_terraform_or_identity_metadata(
    repository_root: Path,
) -> None:
    forbidden = {
        "tfplan",
        "tfplan.identity",
        "backend.hcl",
        "demo-ci.tfvars",
        "active-pointer",
        "model-objects",
        "runtime-contract",
        "live-images",
        "artifacts/deploy/smoke",
    }
    for workflow_name in ("deploy-demo.yml", "destroy-demo.yml", "terraform-plan.yml"):
        source = (repository_root / ".github/workflows" / workflow_name).read_text()
        workflow = yaml.load(source, Loader=yaml.BaseLoader)
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if "actions/upload-artifact@" not in str(step.get("uses", "")):
                    continue
                uploaded = str(step.get("with", {}).get("path", ""))
                if any(value in uploaded for value in forbidden):
                    condition = str(step.get("if", ""))
                    assert "inputs.governance_mode == 'team_protected'" in condition
                    assert "solo_portfolio" not in condition
    deploy = (repository_root / ".github/workflows/deploy-demo.yml").read_text()
    assert deploy.count("./scripts/confidential_plan_transfer.sh upload") == 2
    assert deploy.count("./scripts/confidential_plan_transfer.sh download") == 2
    assert "mask-aws-account-id: false" not in deploy

    publish = (repository_root / ".github/workflows/publish-images.yml").read_text()
    assert "path: artifacts/image-transfer.enc" in publish
    assert "path: artifacts/image-build/" not in publish
    assert "IMAGE_TRANSFER_PRIVATE_KEY_B64" in publish
    assert "--private-key-stdin" in publish
    publish_workflow = yaml.load(publish, Loader=yaml.BaseLoader)
    for step in publish_workflow["jobs"]["publish"]["steps"]:
        if str(step.get("with", {}).get("path", "")) == "artifacts/image-release/":
            assert "inputs.governance_mode == 'team_protected'" in str(step.get("if", ""))

    container_workflow = yaml.load(
        (repository_root / ".github/workflows/container-security.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    metadata_upload = next(
        step
        for step in container_workflow["jobs"]["build-and-scan"]["steps"]
        if "actions/upload-artifact@" in str(step.get("uses", ""))
    )
    assert str(metadata_upload["with"]["path"]) == (
        "artifacts/container-security/${{ matrix.component }}/"
    )
    assert "vars.DEPLOYMENT_GOVERNANCE_MODE == 'team_protected'" in str(metadata_upload["if"])


def _confidential_transfer_keys() -> tuple[str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    private_der = private.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_der = private.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return (
        base64.b64encode(public_der).decode("ascii"),
        base64.b64encode(private_der).decode("ascii"),
    )


def test_confidential_image_transfer_is_authenticated_atomic_and_private(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    public_key, private_key = _confidential_transfer_keys()
    plaintext = tmp_path / "image-transfer.tar"
    encrypted = tmp_path / "image-transfer.enc"
    recovered = tmp_path / "recovered.tar"
    secret_marker = b"image metadata must never be publicly readable"
    plaintext.write_bytes(secret_marker * 100)

    encrypt_result = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "scripts.confidential_artifact",
            "encrypt",
            "--input",
            str(plaintext),
            "--output",
            str(encrypted),
            "--public-key-b64",
            public_key,
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert encrypt_result.returncode == 0
    assert secret_marker not in encrypted.read_bytes()
    assert os.stat(encrypted).st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob(".image-transfer.enc.*"))

    decrypt_result = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "scripts.confidential_artifact",
            "decrypt",
            "--input",
            str(encrypted),
            "--output",
            str(recovered),
            "--private-key-stdin",
        ],
        cwd=repository_root,
        input=private_key,
        check=False,
        capture_output=True,
        text=True,
    )
    assert decrypt_result.returncode == 0
    assert recovered.read_bytes() == plaintext.read_bytes()
    assert os.stat(recovered).st_mode & 0o777 == 0o600
    assert private_key not in decrypt_result.stdout
    assert private_key not in decrypt_result.stderr


def test_confidential_image_transfer_rejects_tampering_and_wrong_private_key(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    public_key, private_key = _confidential_transfer_keys()
    _, wrong_private_key = _confidential_transfer_keys()
    plaintext = tmp_path / "source"
    encrypted = tmp_path / "transfer.enc"
    plaintext.write_bytes(b"verified image transfer")
    subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "scripts.confidential_artifact",
            "encrypt",
            "--input",
            str(plaintext),
            "--output",
            str(encrypted),
            "--public-key-b64",
            public_key,
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
        text=True,
    )

    for label, key, mutate in (
        ("wrong-key", wrong_private_key, False),
        ("tampered", private_key, True),
    ):
        candidate = tmp_path / f"{label}.enc"
        candidate.write_bytes(encrypted.read_bytes())
        if mutate:
            content = bytearray(candidate.read_bytes())
            content[10] ^= 1
            candidate.write_bytes(content)
        output = tmp_path / f"{label}.out"
        result = subprocess.run(
            [
                ".venv/bin/python",
                "-m",
                "scripts.confidential_artifact",
                "decrypt",
                "--input",
                str(candidate),
                "--output",
                str(output),
                "--private-key-stdin",
            ],
            cwd=repository_root,
            input=key,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert not output.exists()
        assert not list(tmp_path.glob(f".{label}.out.*"))
        assert key not in result.stdout
        assert key not in result.stderr


def test_destroy_mode_cannot_be_omitted_or_downgraded(
    repository_root: Path,
) -> None:
    result = subprocess.run(
        [str(repository_root / "scripts/safe_destroy.sh")],
        cwd=repository_root,
        env={"CONFIRM_DESTROY": "YES"},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "DEPLOYMENT_GOVERNANCE_MODE is required" in result.stdout
    source = (repository_root / "scripts/safe_destroy.sh").read_text()
    assert "${DEPLOYMENT_GOVERNANCE_MODE:-team_protected}" not in source
    assert "DESTROY TEAM modelguard-ai demo" in source
    assert "DESTROY SOLO modelguard-ai demo" in source
    assert "output -raw deployment_governance_mode" in source
    assert '"$deployed_mode" != "$governance_mode"' in source

    workflow = yaml.load(
        (repository_root / ".github/workflows/destroy-demo.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["governance_mode"]["required"] == "true"
    assert workflow["jobs"]["destroy-apply"]["environment"] == "demo-destroy"
    apply_source = str(workflow["jobs"]["destroy-apply"])
    assert "scripts.deployment_governance evidence" in apply_source
    assert "REVIEWED_DESTROY_PLAN_SHA256" in apply_source
    assert "REVIEWED_DESTROY_RUN_IDENTITY" in apply_source
    assert "DEPLOYMENT_GOVERNANCE_MODE" in apply_source
    assert "output -raw deployment_governance_mode" in str(workflow["jobs"]["destroy-plan"])


def test_saved_apply_scripts_reject_governance_mode_substitution(
    repository_root: Path,
) -> None:
    ci_apply = (repository_root / "scripts/ci_apply_saved_plan.sh").read_text()
    human_apply = (repository_root / "scripts/safe_apply.sh").read_text()
    human_destroy = (repository_root / "scripts/safe_destroy.sh").read_text()
    terraform = (repository_root / "infrastructure/environments/demo/variables.tf").read_text()
    outputs = (repository_root / "infrastructure/environments/demo/outputs.tf").read_text()

    for source in (ci_apply, human_apply, human_destroy):
        assert ".deployment_governance_mode" in source
        assert "output -raw deployment_governance_mode" in source
    assert 'variable "deployment_governance_mode"' in terraform
    assert 'output "deployment_governance_mode"' in outputs

    deploy = (repository_root / ".github/workflows/deploy-demo.yml").read_text()
    destroy = (repository_root / ".github/workflows/destroy-demo.yml").read_text()
    plan = (repository_root / ".github/workflows/terraform-plan.yml").read_text()
    for source in (deploy, destroy, plan):
        assert '--governance-mode "$GOVERNANCE_MODE"' in source
    assert deploy.count("DEPLOYMENT_GOVERNANCE_MODE: ${{ inputs.governance_mode }}") == 2
    assert destroy.count("DEPLOYMENT_GOVERNANCE_MODE: ${{ inputs.governance_mode }}") == 1


def test_rollback_record_persists_mode_and_refuses_downgrade_by_variable_change(
    repository_root: Path,
) -> None:
    record = (repository_root / "scripts/deployment_record.py").read_text()
    deploy = (repository_root / ".github/workflows/deploy-demo.yml").read_text()
    rollback = (repository_root / ".github/workflows/rollback-demo.yml").read_text()

    assert 'schema_version: Literal["modelguard.last-known-good.v2"]' in record
    assert "deployment_governance_mode: Literal" in record
    assert '--governance-mode "$GOVERNANCE_MODE"' in deploy
    assert ".deployment_governance_mode" in deploy
    assert "steps.record.outputs.deployment_governance_mode" in rollback
    assert 'test "$RECORDED_GOVERNANCE_MODE" = "$GOVERNANCE_MODE"' in rollback
