from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from decisionvault.memory_telemetry import threshold_profile_catalog


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render the latest persisted memory-quality calibration run into a "
            "promotion-review artifact. This tool never changes thresholds."
        )
    )
    parser.add_argument("--database-url-file", type=Path, required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/memory-calibration-promotion-review.json"),
    )
    args = parser.parse_args()

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
                SELECT run_id::STRING, source, calibration_revision, lookback_days,
                       minimum_samples, minimum_success_retention,
                       maximum_harmful_rate, decision_rows, labeled_outcomes,
                       observed_samples, champion_successes, champion_harmful,
                       recommendation, recommended_profile, challengers, generated_at
                FROM decision_memory_quality_calibration_runs
                ORDER BY generated_at DESC, run_id DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        payload = {
            "promotion_status": "NO_CALIBRATION_RUN",
            "automatic_threshold_mutation": False,
        }
    else:
        profile_name = str(row[13]) if row[13] is not None else None
        catalog = threshold_profile_catalog()
        challenger = catalog.get(profile_name or "")
        recommendation = str(row[12])
        promotion_status = (
            "REVIEW_REQUIRED"
            if recommendation == "RECOMMEND_CHALLENGER_SHADOW_ONLY"
            and challenger is not None
            else "NO_PROMOTION"
        )
        challengers = row[14] or []
        if isinstance(challengers, str):
            try:
                challengers = json.loads(challengers)
            except json.JSONDecodeError:
                challengers = []
        payload = {
            "promotion_status": promotion_status,
            "automatic_threshold_mutation": False,
            "run_id": str(row[0]),
            "source": str(row[1]),
            "calibration_revision": str(row[2]),
            "lookback_days": int(row[3]),
            "minimum_samples": int(row[4]),
            "minimum_success_retention": float(row[5]),
            "maximum_harmful_rate": float(row[6]),
            "decision_rows": int(row[7]),
            "labeled_outcomes": int(row[8]),
            "observed_samples": int(row[9]),
            "champion_successes": int(row[10]),
            "champion_harmful": int(row[11]),
            "recommendation": recommendation,
            "recommended_profile": profile_name,
            "champion_profile": asdict(catalog["champion"]),
            "challenger_profile": asdict(challenger) if challenger is not None else None,
            "challengers": challengers,
            "generated_at": row[15].isoformat(),
            "required_promotion_gates": [
                "human review of the persisted recommendation",
                "explicit source-code threshold change",
                "full local test suite",
                "production semantic benchmark 14/14",
                "adaptive adversarial/concurrency smoke 13/13",
                "hosted readiness HTTP 200",
                "hosted demo/governance regression",
                "GitHub CI success",
            ],
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"promotion_review_output={args.output}")
    print(f"promotion_status={payload['promotion_status']}")
    print("automatic_threshold_mutation=False")
    print("memory_calibration_promotion_review=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
