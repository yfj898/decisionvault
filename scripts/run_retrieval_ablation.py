#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from decisionvault.retrieval_ablation import (
    DEFAULT_K_VALUES,
    DEFAULT_PRESSURES,
    evaluate_matrix,
    markdown_report,
)


def _csv_ints(value: str) -> tuple[int, ...]:
    try:
        parsed = tuple(int(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected comma-separated integers") from exc
    if not parsed:
        raise argparse.ArgumentTypeError("at least one integer is required")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic DecisionVault retrieval-pipeline ablation."
    )
    parser.add_argument(
        "--k",
        type=_csv_ints,
        default=DEFAULT_K_VALUES,
        help="comma-separated ANN K values (default: 5,10,32)",
    )
    parser.add_argument(
        "--pressure",
        type=_csv_ints,
        default=DEFAULT_PRESSURES,
        help="comma-separated distractor/crowding levels (default: 0,4,12,40)",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
    )
    args = parser.parse_args(argv)

    report = evaluate_matrix(k_values=args.k, pressures=args.pressure)
    if args.format == "markdown":
        print(markdown_report(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
