from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from decisionvault.memory_telemetry import calibrate_from_telemetry_rows


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

    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    cfg = conninfo_to_dict(args.database_url_file.read_text(encoding="utf-8").strip())
    cfg["sslrootcert"] = str(args.ca_file.resolve())
    cfg["connect_timeout"] = "5"
    cfg["options"] = "-c statement_timeout=30000"
    conn = psycopg.connect(**cfg)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT d.source, d.decided_at, d.scope_level, d.selected_strategy,
                       d.executable, d.memory_influenced, d.memory_resolution,
                       d.memory_conflict, d.quality_features,
                       o.outcome, o.effectiveness, o.confidence,
                       o.observed_at, o.recorded_at
                FROM decision_memory_quality_decisions d
                LEFT JOIN decision_memory_quality_outcomes o
                  ON o.decision_snapshot_id = d.decision_snapshot_id
                WHERE d.source = %s
                  AND d.decided_at >= now() - (%s * INTERVAL '1 day')
                ORDER BY d.decided_at
                """,
                (args.source, args.lookback_days),
            )
            rows = [
                {
                    "source": row[0],
                    "decided_at": row[1].isoformat(),
                    "scope_level": row[2],
                    "selected_strategy": row[3],
                    "executable": bool(row[4]),
                    "memory_influenced": bool(row[5]),
                    "memory_resolution": row[6],
                    "memory_conflict": bool(row[7]),
                    "quality_features": row[8] or {},
                    "outcome": row[9],
                    "effectiveness": float(row[10]) if row[10] is not None else None,
                    "confidence": float(row[11]) if row[11] is not None else None,
                    "observed_at": row[12].isoformat() if row[12] is not None else None,
                    "recorded_at": row[13].isoformat() if row[13] is not None else None,
                }
                for row in cur.fetchall()
            ]
    finally:
        conn.close()

    summary = calibrate_from_telemetry_rows(
        rows,
        source=args.source,
        minimum_samples=args.minimum_samples,
        minimum_success_retention=args.minimum_success_retention,
        maximum_harmful_rate=args.maximum_harmful_rate,
    )
    payload = {
        "calibration": asdict(summary),
        "lookback_days": args.lookback_days,
        "minimum_samples": args.minimum_samples,
        "minimum_success_retention": args.minimum_success_retention,
        "maximum_harmful_rate": args.maximum_harmful_rate,
        "decision_rows": len(rows),
        "labeled_outcomes": sum(row["outcome"] is not None for row in rows),
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
