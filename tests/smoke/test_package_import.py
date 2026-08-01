"""Smoke tests for the installed package skeleton."""

from importlib import import_module
from importlib.metadata import version

import modelguard
from modelguard.version import __version__


def test_package_version_matches_distribution_metadata() -> None:
    assert modelguard.__version__ == __version__ == version("modelguard-ai")


def test_phase_package_skeleton_is_importable() -> None:
    subpackages = (
        "api",
        "core",
        "dashboard",
        "data",
        "inference",
        "monitoring",
        "storage",
        "training",
    )

    for subpackage in subpackages:
        import_module(f"modelguard.{subpackage}")
