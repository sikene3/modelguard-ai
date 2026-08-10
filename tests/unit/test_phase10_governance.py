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


def test_publication_refreshes_only_bounded_inspect_evidence_after_remote_tagging(
    repository_root: Path,
) -> None:
    publish_path = repository_root / ".github/workflows/publish-images.yml"
    source = publish_path.read_text(encoding="utf-8")
    workflow = yaml.load(source, Loader=yaml.BaseLoader)
    publish_job = workflow["jobs"]["publish"]
    tag_step = next(
        step
        for step in publish_job["steps"]
        if step.get("name") == "Tag and push each already-scanned image without rebuilding"
    )
    tag_script = str(tag_step["run"])

    assert tag_script.count('docker image inspect "$remote_ref"') == 1
    assert "RepoTags" in tag_script and "RepoDigests" in tag_script
    assert "Config:{User:.Config.User,Labels:.Config.Labels}" in tag_script
    assert "Env:.Config.Env" not in tag_script
    assert "docker build" not in str(publish_job)
    assert "security_scan.sh" not in str(publish_job)
    assert (
        source.index('docker tag "$local_ref" "$remote_ref"')
        < source.index('docker image inspect "$remote_ref"')
        < source.index("Bind ECR digests, source labels, SBOMs, and Dockerfiles")
    )


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
    assert "output -raw deployment_governance_mode" not in source
    assert ".deployment_governance_mode | select(" in source
    assert "classify-destroy-plan-source-state" in source

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
    destroy_plan = str(workflow["jobs"]["destroy-plan"])
    assert "output -raw deployment_governance_mode" not in destroy_plan
    assert "classify-destroy-plan-source-state" in destroy_plan


def test_saved_apply_scripts_reject_governance_mode_substitution(
    repository_root: Path,
) -> None:
    ci_apply = (repository_root / "scripts/ci_apply_saved_plan.sh").read_text()
    human_apply = (repository_root / "scripts/safe_apply.sh").read_text()
    human_destroy = (repository_root / "scripts/safe_destroy.sh").read_text()
    terraform = (repository_root / "infrastructure/environments/demo/variables.tf").read_text()
    outputs = (repository_root / "infrastructure/environments/demo/outputs.tf").read_text()

    for source in (ci_apply, human_apply):
        assert ".deployment_governance_mode" in source
        assert "output -raw deployment_governance_mode" in source
    assert ".deployment_governance_mode" in human_destroy
    assert "output -raw deployment_governance_mode" not in human_destroy
    assert "classify-destroy-plan-source-state" in human_destroy
    assert 'if [[ "$PLAN_STAGE" == "activation" ]]' in ci_apply
    assert 'variable "deployment_governance_mode"' in terraform
    assert 'output "deployment_governance_mode"' in outputs

    deploy = (repository_root / ".github/workflows/deploy-demo.yml").read_text()
    destroy = (repository_root / ".github/workflows/destroy-demo.yml").read_text()
    plan = (repository_root / ".github/workflows/terraform-plan.yml").read_text()
    for source in (deploy, destroy, plan):
        assert '--governance-mode "$GOVERNANCE_MODE"' in source
    assert deploy.count("DEPLOYMENT_GOVERNANCE_MODE: ${{ inputs.governance_mode }}") == 2
    assert destroy.count("DEPLOYMENT_GOVERNANCE_MODE: ${{ inputs.governance_mode }}") == 1


@pytest.mark.parametrize(
    ("script_name", "confirmation"),
    (("safe_apply.sh", "CONFIRM_APPLY"), ("safe_destroy.sh", "CONFIRM_DESTROY")),
)
@pytest.mark.parametrize(
    ("filename", "mode", "content", "expected"),
    (
        ("demo.auto.tfvars", 0o600, 'deployment_stage = "prerequisites"\n', "*.tfvars.json"),
        ("demo-ci.tfvars.json", 0o644, "{}\n", "exact mode 0600"),
        ("demo-ci.tfvars.json", 0o600, "{not-json}\n", "valid JSON"),
    ),
)
def test_human_helpers_reject_nonrenderer_tfvars_before_any_cloud_command(
    repository_root: Path,
    tmp_path: Path,
    script_name: str,
    confirmation: str,
    filename: str,
    mode: int,
    content: str,
    expected: str,
) -> None:
    backend = tmp_path / "backend.hcl"
    backend.write_text("placeholder = true\n", encoding="utf-8")
    tfvars = tmp_path / filename
    tfvars.write_text(content, encoding="utf-8")
    tfvars.chmod(mode)
    inventory_directory = tmp_path / "inventory"
    inventory_directory.mkdir(mode=0o700)
    environment = os.environ.copy()
    environment.update(
        {
            confirmation: "YES",
            "EXPECTED_AWS_ACCOUNT_ID": "123456789012",
            "AWS_REGION": "us-east-1",
            "BACKEND_BUCKET_NAME": "modelguard-ai-terraform-state-123456789012-us-east-1",
            "BACKEND_CONFIG": str(backend),
            "TFVARS_FILE": str(tfvars),
            "POST_DESTROY_INVENTORY": str(inventory_directory / "initial.json"),
            "PLAN_STAGE": "prerequisites",
            "AUTO_DESTROY_DATE": "2099-01-01",
            "TEARDOWN_AUTHORIZED": "true",
            "AWS_PROFILE": "modelguard-bootstrap",
            "DEPLOYMENT_GOVERNANCE_MODE": "solo_portfolio",
        }
    )

    result = subprocess.run(
        [str(repository_root / "scripts" / script_name)],
        cwd=repository_root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert expected in result.stdout
    assert "terraform" not in result.stderr.lower()


def test_human_helpers_render_only_sealed_redacted_plan_evidence(
    repository_root: Path,
) -> None:
    apply_source = (repository_root / "scripts/safe_apply.sh").read_text(encoding="utf-8")
    destroy_source = (repository_root / "scripts/safe_destroy.sh").read_text(encoding="utf-8")

    for source in (apply_source, destroy_source):
        assert "umask 077" in source
        assert "scripts.plan_evidence" in source
        assert '--plan "$plan_path"' in source
        assert 'show -json "$plan_path" 2>/dev/null' in source
        assert 'show "$plan_path"' not in source
        assert '"$plan_path" >/dev/null 2>&1' in source

    assert 'review_dir="$(mktemp -d)"' in apply_source
    assert 'chmod 0700 "$review_dir"' in apply_source
    assert 'evidence_json="$review_dir/plan.redacted.json"' in apply_source
    assert 'evidence_markdown="$review_dir/plan.redacted.md"' in apply_source
    assert 'pointer_response="$review_dir/active-pointer.json"' in apply_source
    assert 'evidence_json="$plan_path.redacted.json"' not in apply_source
    assert apply_source.count("trap cleanup_review_dir EXIT") == 1
    assert "trap 'rm -f" not in apply_source
    assert 'rmdir -- "$review_dir"' in apply_source

    assert 'evidence_json="$plan_path.redacted.json"' in destroy_source
    assert 'evidence_markdown="$plan_path.redacted.md"' in destroy_source
    target_refusal = destroy_source.index("for planned_output in")
    destroy_plan = destroy_source.index('terraform -chdir="$env_dir" plan')
    assert target_refusal < destroy_plan
    assert "a destroy plan, identity, or redacted-evidence target already exists" in destroy_source
    assert "\ntrap " not in destroy_source
    assert '-out="$plan_path" >/dev/null 2>&1' in destroy_source
    assert "raw Terraform output was suppressed" in apply_source
    assert "raw Terraform output was suppressed" in destroy_source


def test_human_apply_temp_review_survives_existing_evidence_and_cleans_on_rerun(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    harness = tmp_path / "repo"
    scripts_dir = harness / "scripts"
    environment_dir = harness / "infrastructure" / "environments" / "demo"
    fake_bin = tmp_path / "bin"
    review_parent = tmp_path / "reviews"
    for directory in (scripts_dir, environment_dir, fake_bin, review_parent):
        directory.mkdir(parents=True, exist_ok=True)

    apply_script = scripts_dir / "safe_apply.sh"
    apply_script.write_text(
        (repository_root / "scripts/safe_apply.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    apply_script.chmod(0o700)

    terraform_stub = fake_bin / "terraform"
    terraform_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'case "$*" in\n'
        "  *\"workspace show\"*) printf 'default\\n' ;;\n"
        "  *\"output -raw deployment_governance_mode\"*) printf 'solo_portfolio\\n' ;;\n"
        '  *"show -json"*) printf \'{"format_version":"1.2"}\\n\' ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    terraform_stub.chmod(0o700)

    aws_stub = fake_bin / "aws"
    aws_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'case "$*" in\n'
        "  *\"sts get-caller-identity\"*) printf '123456789012\\n' ;;\n"
        "  *\"configure get region\"*) printf 'us-east-1\\n' ;;\n"
        '  *"ssm get-parameter"*) printf \'{"Parameter":{}}\\n\' ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    aws_stub.chmod(0o700)

    invocation_log = tmp_path / "review-modes.log"
    uv_stub = fake_bin / "uv"
    uv_stub.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ " $* " == *" scripts.plan_evidence "* ]]; then\n'
        "  output_json=''\n"
        "  output_markdown=''\n"
        "  while (( $# )); do\n"
        '    case "$1" in\n'
        '      --output-json) output_json="$2"; shift 2 ;;\n'
        '      --output-markdown) output_markdown="$2"; shift 2 ;;\n'
        "      *) shift ;;\n"
        "    esac\n"
        "  done\n"
        '  test ! -e "$output_json"\n'
        '  test ! -e "$output_markdown"\n'
        "  cat >/dev/null\n"
        "  printf '{}\\n' >\"$output_json\"\n"
        "  printf '# Redacted plan\\n' >\"$output_markdown\"\n"
        "  printf '%s:%s:%s\\n' \\\n"
        '    "$(stat -c \'%a\' "$(dirname "$output_json")")" \\\n'
        '    "$(stat -c \'%a\' "$output_json")" \\\n'
        '    "$(stat -c \'%a\' "$output_markdown")" >>"$MODELGUARD_TEST_LOG"\n'
        "fi\n",
        encoding="utf-8",
    )
    uv_stub.chmod(0o700)

    backend = tmp_path / "backend.hcl"
    backend.write_text("placeholder = true\n", encoding="utf-8")
    tfvars = tmp_path / "demo-ci.tfvars.json"
    tfvars.write_text('{"deployment_governance_mode":"solo_portfolio"}\n', encoding="utf-8")
    tfvars.chmod(0o600)
    plan = environment_dir / "prerequisites.tfplan"
    manifest = environment_dir / "prerequisites.tfplan.identity.json"
    plan.write_bytes(b"opaque plan")
    manifest.write_text("{}\n", encoding="utf-8")
    (environment_dir / "activation.tfplan").write_bytes(b"opaque activation plan")
    (environment_dir / "activation.tfplan.identity.json").write_text("{}\n", encoding="utf-8")
    persistent_json = environment_dir / "prerequisites.tfplan.redacted.json"
    persistent_markdown = environment_dir / "prerequisites.tfplan.redacted.md"
    persistent_json.write_text('{"persistent":true}\n', encoding="utf-8")
    persistent_markdown.write_text("# Persistent evidence\n", encoding="utf-8")

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "TMPDIR": str(review_parent),
            "MODELGUARD_TEST_LOG": str(invocation_log),
            "CONFIRM_APPLY": "YES",
            "EXPECTED_AWS_ACCOUNT_ID": "123456789012",
            "AWS_REGION": "us-east-1",
            "BACKEND_BUCKET_NAME": "modelguard-ai-terraform-state-123456789012-us-east-1",
            "BACKEND_CONFIG": str(backend),
            "TFVARS_FILE": str(tfvars),
            "PLAN_STAGE": "prerequisites",
            "AWS_PROFILE": "modelguard-bootstrap",
            "DEPLOYMENT_GOVERNANCE_MODE": "solo_portfolio",
        }
    )

    cancelled = subprocess.run(
        [str(apply_script)],
        cwd=harness,
        env=environment,
        input="cancel\n",
        check=False,
        capture_output=True,
        text=True,
    )
    assert cancelled.returncode == 1
    assert not list(review_parent.iterdir())

    rerun = subprocess.run(
        [str(apply_script)],
        cwd=harness,
        env=environment,
        input="prerequisites\n",
        check=False,
        capture_output=True,
        text=True,
    )
    assert rerun.returncode == 0
    assert not list(review_parent.iterdir())
    assert persistent_json.read_text(encoding="utf-8") == '{"persistent":true}\n'
    assert persistent_markdown.read_text(encoding="utf-8") == "# Persistent evidence\n"

    activation_environment = {**environment, "PLAN_STAGE": "activation"}
    activation = subprocess.run(
        [str(apply_script)],
        cwd=harness,
        env=activation_environment,
        input="activation\n",
        check=False,
        capture_output=True,
        text=True,
    )
    assert activation.returncode == 0
    assert not list(review_parent.iterdir())
    assert invocation_log.read_text(encoding="utf-8").splitlines() == [
        "700:600:600",
        "700:600:600",
        "700:600:600",
    ]


def test_human_destroy_refuses_a_preexisting_review_set_before_cloud_access(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    harness = tmp_path / "repo"
    scripts_dir = harness / "scripts"
    environment_dir = harness / "infrastructure" / "environments" / "demo"
    scripts_dir.mkdir(parents=True)
    environment_dir.mkdir(parents=True)
    destroy_script = scripts_dir / "safe_destroy.sh"
    destroy_script.write_text(
        (repository_root / "scripts/safe_destroy.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    destroy_script.chmod(0o700)
    existing = environment_dir / "destroy.tfplan.redacted.md"
    existing.write_text("# Sealed prior review\n", encoding="utf-8")
    inventory_directory = tmp_path / "inventory"
    inventory_directory.mkdir(mode=0o700)

    environment = os.environ.copy()
    environment.update(
        {
            "CONFIRM_DESTROY": "YES",
            "EXPECTED_AWS_ACCOUNT_ID": "123456789012",
            "AWS_REGION": "us-east-1",
            "BACKEND_BUCKET_NAME": "modelguard-ai-terraform-state-123456789012-us-east-1",
            "BACKEND_CONFIG": str(tmp_path / "not-read-backend.hcl"),
            "TFVARS_FILE": str(tmp_path / "not-read.tfvars.json"),
            "POST_DESTROY_INVENTORY": str(inventory_directory / "initial.json"),
            "AUTO_DESTROY_DATE": "2099-01-01",
            "TEARDOWN_AUTHORIZED": "true",
            "AWS_PROFILE": "modelguard-bootstrap",
            "DEPLOYMENT_GOVERNANCE_MODE": "solo_portfolio",
        }
    )
    result = subprocess.run(
        [str(destroy_script)],
        cwd=harness,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "redacted-evidence target already exists" in result.stdout
    assert existing.read_text(encoding="utf-8") == "# Sealed prior review\n"
    assert "not found" not in result.stderr.lower()


def test_human_activation_rechecks_live_pointer_at_the_final_boundary(
    repository_root: Path,
) -> None:
    source = (repository_root / "scripts/safe_apply.sh").read_text(encoding="utf-8")
    confirmation = source.index("read -r answer")
    final_plan_check = source.rindex('"${guard[@]}" verify-plan')
    pointer_read = source.index("aws ssm get-parameter")
    pointer_binding = source.index('"${guard[@]}" verify-active-pointer')
    final_identity = source.rindex("\nverify_human_identity\n")
    apply = source.index('terraform -chdir="$env_dir" apply')

    assert confirmation < final_plan_check < pointer_read < pointer_binding < final_identity < apply
    assert 'if [[ "$PLAN_STAGE" = "activation" ]]' in source
    assert "--name /modelguard-ai/demo/models/active" in source
    assert '--profile "$AWS_PROFILE"' in source
    assert '--region "$AWS_REGION"' in source
    assert "--no-with-decryption" in source
    assert "--no-cli-pager" in source
    assert "--output json" in source
    assert source.count("aws ssm get-parameter") == 1
    assert source.count("\nverify_human_identity\n") == 2


def test_human_destroy_rechecks_exact_identity_immediately_before_apply(
    repository_root: Path,
) -> None:
    source = (repository_root / "scripts/safe_destroy.sh").read_text(encoding="utf-8")
    final_confirmation = source.index("read -r final")
    final_plan_check = source.rindex('"${guard[@]}" verify-plan')
    final_identity = source.rindex("\nverify_human_identity\n")
    apply = source.index('terraform -chdir="$env_dir" apply')

    assert final_confirmation < final_plan_check < final_identity < apply
    assert source.count("\nverify_human_identity\n") == 2
    assert "browser-login identity verification failed" in source
    assert "2>/dev/null" in source


def test_human_operator_docs_bind_exact_json_and_governance_contract(
    repository_root: Path,
) -> None:
    for relative in ("docs/08_AWS_DEPLOYMENT_ORDER.md", "docs/TERRAFORM_AWS.md"):
        source = (repository_root / relative).read_text(encoding="utf-8")
        assert "scripts.render_ci_terraform" in source
        assert "demo-ci.tfvars.json" in source
        assert "0600" in source
        assert "DEPLOYMENT_GOVERNANCE_MODE=solo_portfolio" in source
        assert "action-only redacted evidence" in source
        assert "TFVARS_FILE=/absolute/path/demo.auto.tfvars" not in source

    terraform_docs = (repository_root / "docs/TERRAFORM_AWS.md").read_text(encoding="utf-8")
    cost_docs = (repository_root / "docs/04_COST_CONTROL.md").read_text(encoding="utf-8")
    for source in (
        terraform_docs,
        (repository_root / "scripts/safe_apply.sh").read_text(encoding="utf-8"),
        (repository_root / "scripts/safe_destroy.sh").read_text(encoding="utf-8"),
    ):
        assert "-input=false" in source
        assert "-lockfile=readonly" in source
    assert "umask 077" in terraform_docs
    assert "POST_DESTROY_INVENTORY" in cost_docs
    assert "different create-only target" in cost_docs
    assert "./scripts/safe_destroy.sh" not in cost_docs


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


def _run_ci_apply_identity_case(
    repository_root: Path,
    tmp_path: Path,
    *,
    caller_arn: str,
    expected_role_arn: str = (
        "arn:aws:iam::123456789012:role/modelguard-ai/bootstrap/modelguard-ai-ci-deploy"
    ),
    aws_profile: str | None = None,
    fail_identity_lookup: bool = False,
    fail_cleanup: bool = False,
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    harness = tmp_path / "repo"
    scripts_dir = harness / "scripts"
    environment_dir = harness / "infrastructure" / "environments" / "demo"
    fake_bin = tmp_path / "bin"
    runtime_parent = tmp_path / "runtime"
    for directory in (scripts_dir, environment_dir, fake_bin, runtime_parent):
        directory.mkdir(parents=True, exist_ok=True)
    runtime_parent.chmod(0o700)

    apply_script = scripts_dir / "ci_apply_saved_plan.sh"
    apply_script.write_text(
        (repository_root / "scripts/ci_apply_saved_plan.sh").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    apply_script.chmod(0o700)

    aws_log = tmp_path / "aws.log"
    terraform_log = tmp_path / "terraform.log"
    stubs = {
        "git": "#!/usr/bin/env bash\nprintf '%s\\n' \"$MODELGUARD_TEST_COMMIT\"\n",
        "uv": "#!/usr/bin/env bash\nexit 0\n",
        "terraform": (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'printf \'%s\\n\' "$*" >>"$MODELGUARD_TERRAFORM_LOG"\n'
            'case "$*" in\n'
            "  *\"workspace show\"*) printf 'default\\n' ;;\n"
            "esac\n"
        ),
        "aws": (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'printf \'%s\\n\' "$*" >>"$MODELGUARD_AWS_LOG"\n'
            'if [[ "${MODELGUARD_FAIL_IDENTITY:-false}" == true ]]; then\n'
            "  printf 'private-error-sentinel\\n' >&2\n"
            "  exit 7\n"
            "fi\n"
            'printf \'{"Account":"123456789012","Arn":"%s"}\\n\' "$MODELGUARD_CALLER_ARN"\n'
        ),
    }
    for name, source in stubs.items():
        stub = fake_bin / name
        stub.write_text(source, encoding="utf-8")
        stub.chmod(0o700)
    if fail_cleanup:
        rm_stub = fake_bin / "rm"
        rm_stub.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        rm_stub.chmod(0o700)

    backend = tmp_path / "backend.hcl"
    tfvars = tmp_path / "demo-ci.tfvars.json"
    plan = tmp_path / "prerequisites.tfplan"
    manifest = tmp_path / "prerequisites.tfplan.identity.json"
    backend.write_text("placeholder = true\n", encoding="utf-8")
    tfvars.write_text('{"deployment_governance_mode":"solo_portfolio"}\n', encoding="utf-8")
    plan.write_bytes(b"opaque-plan")
    manifest.write_text("{}\n", encoding="utf-8")
    for private_file in (backend, tfvars, plan, manifest):
        private_file.chmod(0o600)

    commit = "a" * 40
    environment = os.environ.copy()
    environment.pop("AWS_PROFILE", None)
    environment.pop("AWS_DEFAULT_PROFILE", None)
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "MODELGUARD_GITHUB_ENVIRONMENT": "demo",
            "CONFIRM_APPLY": "YES",
            "EXPECTED_AWS_ACCOUNT_ID": "123456789012",
            "EXPECTED_AWS_ROLE_ARN": expected_role_arn,
            "AWS_REGION": "us-east-1",
            "BACKEND_BUCKET_NAME": "modelguard-ai-terraform-state-123456789012-us-east-1",
            "BACKEND_CONFIG": str(backend),
            "TFVARS_FILE": str(tfvars),
            "PLAN_STAGE": "prerequisites",
            "PLAN_FILE": str(plan),
            "PLAN_MANIFEST": str(manifest),
            "DEPLOYMENT_GOVERNANCE_MODE": "solo_portfolio",
            "GITHUB_SHA": commit,
            "MODELGUARD_TEST_COMMIT": commit,
            "MODELGUARD_CALLER_ARN": caller_arn,
            "MODELGUARD_FAIL_IDENTITY": str(fail_identity_lookup).lower(),
            "MODELGUARD_AWS_LOG": str(aws_log),
            "MODELGUARD_TERRAFORM_LOG": str(terraform_log),
            "TMPDIR": str(runtime_parent),
        }
    )
    if aws_profile is not None:
        environment["AWS_PROFILE"] = aws_profile

    result = subprocess.run(
        [str(apply_script)],
        cwd=harness,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if not fail_cleanup:
        assert list(runtime_parent.iterdir()) == []
    return (
        result,
        aws_log.read_text(encoding="utf-8") if aws_log.exists() else "",
        terraform_log.read_text(encoding="utf-8") if terraform_log.exists() else "",
    )


def test_ci_apply_accepts_only_the_exact_oidc_deploy_role(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    result, aws_log, terraform_log = _run_ci_apply_identity_case(
        repository_root,
        tmp_path,
        caller_arn=("arn:aws:sts::123456789012:assumed-role/modelguard-ai-ci-deploy/phase10-run"),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '{"status":"passed","operation":"saved-plan-apply"}'
    assert aws_log.count("sts get-caller-identity --region us-east-1") == 2
    assert " apply " in f" {terraform_log} "


@pytest.mark.parametrize(
    "caller_arn",
    (
        "arn:aws:sts::123456789012:assumed-role/another-role/phase10-run",
        "arn:aws:sts::123456789012:assumed-role/modelguard-ai-ci-deploy/x",
        "arn:aws:iam::123456789012:role/modelguard-ai/bootstrap/modelguard-ai-ci-deploy",
    ),
)
def test_ci_apply_rejects_wrong_or_malformed_caller_before_terraform(
    repository_root: Path,
    tmp_path: Path,
    caller_arn: str,
) -> None:
    result, aws_log, terraform_log = _run_ci_apply_identity_case(
        repository_root, tmp_path, caller_arn=caller_arn
    )

    assert result.returncode == 1
    assert "sts get-caller-identity" in aws_log
    assert terraform_log == ""
    assert caller_arn not in result.stdout + result.stderr


def test_ci_apply_fails_closed_when_private_identity_cleanup_fails(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    result, aws_log, terraform_log = _run_ci_apply_identity_case(
        repository_root,
        tmp_path,
        caller_arn=("arn:aws:sts::123456789012:assumed-role/modelguard-ai-ci-deploy/phase10-run"),
        fail_cleanup=True,
    )

    assert result.returncode == 1
    assert "Temporary workflow identity cleanup failed" in result.stderr
    assert aws_log.count("sts get-caller-identity") == 2
    assert " apply " in f" {terraform_log} "


def test_ci_apply_rejects_wrong_expected_role_and_named_profile_before_aws(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    wrong_role, aws_log, terraform_log = _run_ci_apply_identity_case(
        repository_root,
        tmp_path / "wrong-role",
        caller_arn=("arn:aws:sts::123456789012:assumed-role/modelguard-ai-ci-deploy/phase10-run"),
        expected_role_arn="arn:aws:iam::123456789012:role/another-role",
    )
    named_profile, profile_aws_log, profile_terraform_log = _run_ci_apply_identity_case(
        repository_root,
        tmp_path / "profile",
        caller_arn=("arn:aws:sts::123456789012:assumed-role/modelguard-ai-ci-deploy/phase10-run"),
        aws_profile="forbidden-profile",
    )

    assert wrong_role.returncode == 1
    assert named_profile.returncode == 1
    assert aws_log == profile_aws_log == ""
    assert terraform_log == profile_terraform_log == ""


def test_ci_apply_suppresses_identity_lookup_diagnostics(
    repository_root: Path,
    tmp_path: Path,
) -> None:
    result, aws_log, terraform_log = _run_ci_apply_identity_case(
        repository_root,
        tmp_path,
        caller_arn=("arn:aws:sts::123456789012:assumed-role/modelguard-ai-ci-deploy/phase10-run"),
        fail_identity_lookup=True,
    )

    assert result.returncode == 1
    assert "OIDC caller identity lookup failed" in result.stderr
    assert "private-error-sentinel" not in result.stdout + result.stderr
    assert "sts get-caller-identity" in aws_log
    assert terraform_log == ""
