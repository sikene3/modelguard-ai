from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from scripts.publication_audit import (
    PARTIAL_CLONE_PROMISOR_PATTERN,
    GitConfigMatch,
    PublicationAuditGitError,
    PublicationAuditRefusal,
    query_partial_clone_promisor_config,
    require_no_partial_clone_or_promisor_config,
)


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
