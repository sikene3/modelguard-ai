#!/usr/bin/env python3
"""Run every repository security scanner while preserving each failure."""

from __future__ import annotations

import argparse
import json

# security-suppression:
# finding=B404
# justification=Only fixed repository scanner commands run without a shell.
# owner=modelguard-maintainers
# expires=2026-10-31
import subprocess  # nosec B404
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

REQUIRED_GATES = ("actionlint", "shellcheck", "checkov", "gitleaks", "trivy-repository")
Runner = Callable[..., subprocess.CompletedProcess[str]]


def run_gates(
    commands: Mapping[str, Sequence[str]],
    *,
    runner: Runner = subprocess.run,
) -> tuple[dict[str, int], bool]:
    """Run every exact required gate and return statuses without masking failures."""

    if set(commands) != set(REQUIRED_GATES):
        raise ValueError("security gate command set is incomplete")
    statuses: dict[str, int] = {}
    for name in REQUIRED_GATES:
        try:
            result = runner(list(commands[name]), check=False, text=True)
            statuses[name] = result.returncode
        except OSError:
            statuses[name] = 127
    return statuses, all(status == 0 for status in statuses.values())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--script", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    script = args.script.resolve()
    commands = {name: [str(script), name] for name in REQUIRED_GATES}
    try:
        statuses, passed = run_gates(commands)
    except ValueError as error:
        print(json.dumps({"status": "refused", "reason": str(error)}), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {"status": "passed" if passed else "failed", "scanner_exit_codes": statuses},
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
