from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from scripts.publication_audit import (
    PARTIAL_CLONE_PROMISOR_PATTERN,
    GitConfigMatch,
    PublicationAuditGitError,
    PublicationAuditRefusal,
    classify_publication_email_match,
    contains_publication_private_key_material,
    query_partial_clone_promisor_config,
    require_no_partial_clone_or_promisor_config,
    require_no_publication_private_key_material,
    require_safe_publication_email_matches,
)


def _address(local: str, domain: str) -> bytes:
    return f"{local}{chr(64)}{domain}".encode()


VERIFIED_NOREPLY = _address("123456+verified-user", "users.noreply.github.com")


def _runner(*, returncode: int, stdout: str = "", stderr: str = ""):
    def run(command: Sequence[str], repository: Path) -> subprocess.CompletedProcess[str]:
        assert tuple(command) == (
            "git",
            "config",
            "--get-regexp",
            PARTIAL_CLONE_PROMISOR_PATTERN,
        )
        assert repository == Path("repository")
        return subprocess.CompletedProcess(
            args=command,
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

    return run


def test_git_config_exit_zero_is_parsed_and_refused() -> None:
    runner = _runner(
        returncode=0,
        stdout="extensions.partialclone origin\nremote.origin.promisor true\n",
    )

    assert query_partial_clone_promisor_config(Path("repository"), runner=runner) == (
        GitConfigMatch(key="extensions.partialclone", value="origin"),
        GitConfigMatch(key="remote.origin.promisor", value="true"),
    )
    with pytest.raises(
        PublicationAuditRefusal,
        match="partial_clone_or_promisor_config_present",
    ):
        require_no_partial_clone_or_promisor_config(Path("repository"), runner=runner)


def test_git_config_exit_one_is_valid_empty_configuration() -> None:
    runner = _runner(returncode=1)

    assert query_partial_clone_promisor_config(Path("repository"), runner=runner) == ()
    require_no_partial_clone_or_promisor_config(Path("repository"), runner=runner)


def test_git_config_exit_greater_than_one_forwards_stderr_and_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    runner = _runner(
        returncode=2,
        stderr="fatal: simulated Git configuration failure\n",
    )

    with pytest.raises(
        PublicationAuditGitError,
        match="git_config_query_failed_exit_2",
    ):
        query_partial_clone_promisor_config(Path("repository"), runner=runner)
    assert capsys.readouterr().err == "fatal: simulated Git configuration failure\n"


@pytest.mark.parametrize("domain", ["fixture.test", "fixture.invalid"])
def test_reserved_test_domains_pass_only_for_test_scoped_blob(domain: str) -> None:
    value = _address("synthetic", domain)

    assert (
        classify_publication_email_match(
            value,
            expected_noreply=VERIFIED_NOREPLY,
            blob_paths=("tests/unit/test_fixture.py",),
        )
        == "synthetic_reserved_test_domain"
    )


@pytest.mark.parametrize(
    "paths",
    [
        ("docs/example.md",),
        ("tests/unit/test_fixture.py", "docs/example.md"),
        (),
    ],
)
def test_reserved_test_domain_fails_outside_tests(paths: tuple[str, ...]) -> None:
    value = _address("synthetic", "fixture.test")

    with pytest.raises(
        PublicationAuditRefusal, match="privacy_history_blob_email_present"
    ) as caught:
        classify_publication_email_match(
            value,
            expected_noreply=VERIFIED_NOREPLY,
            blob_paths=paths,
        )
    assert value.decode() not in str(caught.value)


def test_reserved_test_domain_lookalike_fails() -> None:
    value = _address("synthetic", "fixture.test.example.com")

    with pytest.raises(PublicationAuditRefusal, match="privacy_history_blob_email_present"):
        classify_publication_email_match(
            value,
            expected_noreply=VERIFIED_NOREPLY,
            blob_paths=("tests/unit/test_fixture.py",),
        )


def test_only_exact_verified_noreply_identity_passes() -> None:
    assert (
        classify_publication_email_match(
            VERIFIED_NOREPLY,
            expected_noreply=VERIFIED_NOREPLY,
            blob_paths=("docs/example.md",),
        )
        == "verified_github_noreply"
    )

    other = _address("654321+other-user", "users.noreply.github.com")
    with pytest.raises(PublicationAuditRefusal, match="privacy_history_blob_email_present"):
        classify_publication_email_match(
            other,
            expected_noreply=VERIFIED_NOREPLY,
            blob_paths=("tests/unit/test_fixture.py",),
        )


def test_existing_exact_example_domain_allowance_is_preserved() -> None:
    assert (
        classify_publication_email_match(
            _address("synthetic", "example.invalid"),
            expected_noreply=VERIFIED_NOREPLY,
            blob_paths=("docs/example.md",),
        )
        == "synthetic_example_domain"
    )


def test_mixed_blob_fails_without_disclosing_the_rejected_match() -> None:
    accepted = _address("synthetic", "fixture.test")
    rejected = _address("private", "nonreserved.example.edu")
    blob = b" ".join((accepted, rejected))

    with pytest.raises(
        PublicationAuditRefusal, match="privacy_history_blob_email_present"
    ) as caught:
        require_safe_publication_email_matches(
            blob,
            expected_noreply=VERIFIED_NOREPLY,
            blob_paths=("tests/unit/test_fixture.py",),
        )
    assert rejected.decode() not in str(caught.value)


def _private_key_boundary(
    label: bytes = b"", *, suffix: bytes = b"", hyphen_count: int = 5
) -> bytes:
    prefix = b"-" * hyphen_count + b"BEGIN "
    key_type = label + b" " if label else b""
    key_suffix = b" " + suffix if suffix else b""
    return prefix + key_type + b"PRIVATE " + b"KEY" + key_suffix + b"-" * hyphen_count


def _private_key_footer(label: bytes = b"", *, hyphen_count: int = 5) -> bytes:
    prefix = b"-" * hyphen_count + b"END "
    key_type = label + b" " if label else b""
    return prefix + key_type + b"PRIVATE " + b"KEY" + b"-" * hyphen_count


def _private_key_detector_literal() -> bytes:
    hyphens = b"-" * 5
    return b"secret_pattern='" + hyphens + b"BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY" + hyphens + b"'"


def test_private_key_detector_literal_is_not_key_material() -> None:
    hyphens = b"-" * 5
    detector = _private_key_detector_literal()
    wildcard_detector = hyphens + b"BEGIN [A-Z ]*PRIVATE KEY" + hyphens

    assert contains_publication_private_key_material(detector) is False
    assert contains_publication_private_key_material(wildcard_detector) is False
    require_no_publication_private_key_material(detector + b"\n" + wildcard_detector)


@pytest.mark.parametrize(
    "label",
    [b"", b"RSA", b"DSA", b"EC", b"OPENSSH", b"ENCRYPTED", b"SSH2 ENCRYPTED"],
)
def test_literal_private_key_boundaries_fail_closed(label: bytes) -> None:
    material = _private_key_boundary(label) + b"\ninvalid-payload\n"

    assert contains_publication_private_key_material(material) is True
    with pytest.raises(
        PublicationAuditRefusal,
        match="privacy_history_blob_private_key_present",
    ) as caught:
        require_no_publication_private_key_material(material)
    assert "invalid-payload" not in str(caught.value)


def test_literal_private_key_boundary_suffix_fails_closed() -> None:
    material = _private_key_boundary(b"PGP", suffix=b"BLOCK") + b"\ninvalid-payload\n"

    with pytest.raises(
        PublicationAuditRefusal,
        match="privacy_history_blob_private_key_present",
    ):
        require_no_publication_private_key_material(material)


def test_malformed_and_multiline_private_key_material_is_rejected() -> None:
    malformed_missing_footer = (
        b"    " + _private_key_boundary(b"RSA", hyphen_count=4).lower() + b"\r\n"
        b"not-base64\r\n"
        b"still-sensitive\r\n"
    )
    heredoc = (
        b"secret_value=$(printf '%s' <<'KEY_DATA')\n"
        + _private_key_boundary(b"EC")
        + b"\nnot-base64\n"
        + _private_key_footer(b"EC")
        + b"\nKEY_DATA\n"
    )

    for material in (malformed_missing_footer, heredoc):
        with pytest.raises(
            PublicationAuditRefusal,
            match="privacy_history_blob_private_key_present",
        ):
            require_no_publication_private_key_material(material)


@pytest.mark.parametrize("private_format", ["pkcs8", "openssh", "encrypted"])
def test_real_private_key_in_secret_scanner_script_is_rejected(private_format: str) -> None:
    key = Ed25519PrivateKey.generate()
    if private_format == "openssh":
        material = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        )
    else:
        encryption: serialization.KeySerializationEncryption
        if private_format == "encrypted":
            encryption = serialization.BestAvailableEncryption(b"x" * 32)
        else:
            encryption = serialization.NoEncryption()
        material = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            encryption,
        )
    scanner_script = (
        b"#!/usr/bin/env bash\nset -euo pipefail\n"
        + _private_key_detector_literal()
        + b"\n"
        + material
    )

    with pytest.raises(
        PublicationAuditRefusal,
        match="privacy_history_blob_private_key_present",
    ) as caught:
        require_no_publication_private_key_material(scanner_script)
    assert str(caught.value) == "privacy_history_blob_private_key_present"
