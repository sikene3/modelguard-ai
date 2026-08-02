#!/usr/bin/env python3
"""Export the deterministic Pydantic report contract as portable JSON Schema."""

from __future__ import annotations

import argparse
from pathlib import Path

from modelguard.core.serialization import write_json
from modelguard.monitoring.report import monitoring_report_json_schema


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("contracts/monitoring-report-v1.schema.json"),
    )
    args = parser.parse_args()
    write_json(args.output, monitoring_report_json_schema())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
