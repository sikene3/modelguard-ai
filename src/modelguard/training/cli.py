"""Phase 02 generate, train, inspect, and ordered-verify command line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from modelguard.training.bundle import inspect_bundle, verify_bundle
from modelguard.training.workflow import generate_data_artifacts, train_from_artifacts


def _print_json(value: dict[str, Any]) -> None:
    print(json.dumps(value, allow_nan=False, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="modelguard-train")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser(
        "generate", help="generate and persist the dataset plus canonical split"
    )
    generate_parser.add_argument("--config", type=Path, required=True)
    generate_parser.add_argument("--output-root", type=Path, required=True)

    train_parser = subparsers.add_parser(
        "train", help="train only from already persisted and verified artifacts"
    )
    train_parser.add_argument("--config", type=Path, required=True)
    train_parser.add_argument("--output-root", type=Path, required=True)
    train_parser.add_argument("--repository-root", type=Path, default=Path.cwd())

    inspect_parser = subparsers.add_parser(
        "inspect", help="verify bytes/contracts/identities without loading joblib"
    )
    inspect_parser.add_argument("--bundle", type=Path, required=True)

    verify_parser = subparsers.add_parser(
        "verify", help="ordered verification plus one trusted-origin smoke prediction"
    )
    verify_parser.add_argument("--bundle", type=Path, required=True)
    verify_parser.add_argument(
        "--trusted-origin",
        action="store_true",
        help="confirm the joblib came from a trusted local/publisher origin",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a Phase 02 CLI command and emit one machine-readable result."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "generate":
            paths = generate_data_artifacts(args.config, args.output_root)
            _print_json({"data_artifact_directory": str(paths.root), "status": "generated"})
        elif args.command == "train":
            result = train_from_artifacts(
                args.config,
                args.output_root,
                args.repository_root,
            )
            _print_json(
                {
                    "bundle": str(result.bundle_path),
                    "held_out_average_precision": (
                        result.metrics.held_out_test.average_precision.value
                    ),
                    "held_out_prevalence": result.metrics.held_out_test.prevalence.value,
                    "manifest_sha256": result.identity.manifest_sha256,
                    "mlflow_run_id": result.mlflow_run_id,
                    "model_version": result.identity.model_version,
                    "status": "trained",
                    "threshold": result.threshold.threshold,
                }
            )
        elif args.command == "inspect":
            metadata = inspect_bundle(args.bundle)
            _print_json(
                {
                    "deserialized_model": False,
                    "manifest_sha256": metadata.identity.manifest_sha256,
                    "model_version": metadata.identity.model_version,
                    "status": "valid_metadata",
                    "test_row_count": metadata.metrics.held_out_test.row_count,
                    "threshold": metadata.threshold.threshold,
                }
            )
        else:
            if not args.trusted_origin:
                raise ValueError(
                    "--trusted-origin is required before joblib deserialization; "
                    "checksums do not prove authenticity"
                )
            verified = verify_bundle(args.bundle, trusted_origin=True)
            _print_json(
                {
                    "manifest_sha256": verified.metadata.identity.manifest_sha256,
                    "model_version": verified.metadata.identity.model_version,
                    "smoke_score": verified.smoke_score,
                    "status": "verified",
                    "trusted_origin_confirmed": True,
                }
            )
    except (FileNotFoundError, FileExistsError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
