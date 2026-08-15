from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory_telemetry import (
    MEMORY_QUALITY_CALIBRATION_REVISION,
    calibrate_from_telemetry_rows,
    load_calibration_rows,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Calibrate monotone-stricter memory thresholds from observed production "
            "decision/outcome telemetry. This tool never changes runtime thresholds."
        )
    )
    parser.add_argument("--database-url-file", type=Path, required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument("--source", choices=("AGENT_API", "DEMO", "BENCHMARK"), default="AGENT_API")
    parser.add_argument("--lookback-days", type=int, default=90)
    parser.add_argument("--minimum-samples", type=int, default=30)
    parser.add_argument("--minimum-success-retention", type=float, default=0.95)
    parser.add_argument("--maximum-harmful-rate", type=float, default=0.05)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/memory-telemetry-calibration.json"),
    )
    args = parser.parse_args()
    if args.lookback_days <= 0:
        raise SystemExit("lookback-days must be positive")
    if args.minimum_samples <= 0:
        raise SystemExit("minimum-samples must be positive")
    if not 0.0 <= args.minimum_success_retention <= 1.0:
        raise SystemExit("minimum-success-retention must be between 0 and 1")
    if not 0.0 <= args.maximum_harmful_rate <= 1.0:
        raise SystemExit("maximum-harmful-rate must be between 0 and 1")

    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    cfg = conninfo_to_dict(args.database_url_file.read_text(encoding="utf-8").strip())
    cfg["sslrootcert"] = str(args.ca_file.resolve())
    calibration_database_url = make_conninfo(**cfg)
    rows = load_calibration_rows(
        connection_factory=psycopg_connection_factory(
            calibration_database_url,
            connect_timeout_seconds=5,
            statement_timeout_ms=30000,
        ),
        source=args.source,
        lookback_days=args.lookback_days,
    )

    summary = calibrate_from_telemetry_rows(
        rows,
        source=args.source,
        minimum_samples=args.minimum_samples,
        minimum_success_retention=args.minimum_success_retention,
        maximum_harmful_rate=args.maximum_harmful_rate,
    )
    payload = {
        "calibration_revision": MEMORY_QUALITY_CALIBRATION_REVISION,
        "calibration": asdict(summary),
        "lookback_days": args.lookback_days,
        "minimum_samples": args.minimum_samples,
        "minimum_success_retention": args.minimum_success_retention,
        "maximum_harmful_rate": args.maximum_harmful_rate,
        "decision_rows": len(rows),
        "labeled_outcomes": sum(
            str(row.get("outcome") or "") in {"SUCCESS", "FAILED"} for row in rows
        ),
        "guardrails": [
            "historical telemetry evaluates only monotone-stricter profiles",
            "a different executable challenger strategy is COUNTERFACTUAL_UNOBSERVED",
            "this report is recommendation-only and cannot mutate production thresholds",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"telemetry_calibration_output={args.output}")
    print(f"telemetry_decision_rows={len(rows)}")
    print(f"telemetry_labeled_outcomes={payload['labeled_outcomes']}")
    print(f"telemetry_recommendation={summary.recommendation}")
    print(f"telemetry_recommended_profile={summary.recommended_profile or 'NONE'}")
    print("memory_telemetry_calibration=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
