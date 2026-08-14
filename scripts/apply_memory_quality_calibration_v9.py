from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _statements(sql: str) -> list[str]:
    without_line_comments = "\n".join(
        line.split("--", 1)[0] for line in sql.splitlines()
    )
    return [
        statement.strip()
        for statement in without_line_comments.split(";")
        if statement.strip()
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply append-only memory-quality calibration v9 schema."
    )
    parser.add_argument("--database-url-file", type=Path, required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    args = parser.parse_args()

    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    cfg = conninfo_to_dict(args.database_url_file.read_text(encoding="utf-8").strip())
    cfg["sslrootcert"] = str(args.ca_file.resolve())
    cfg["connect_timeout"] = "5"
    cfg["options"] = "-c statement_timeout=120000"
    statements = _statements(
        (ROOT / "scripts" / "memory_quality_calibration_v9.sql").read_text(
            encoding="utf-8"
        )
    )

    conn = psycopg.connect(**cfg, autocommit=True)
    try:
        with conn.cursor() as cur:
            for index, statement in enumerate(statements, start=1):
                try:
                    cur.execute(statement)
                except Exception as exc:
                    print(
                        f"memory_quality_calibration_v9_statement_{index}="
                        f"FAIL:{type(exc).__name__}"
                    )
                    return 2
    finally:
        conn.close()

    print(f"memory_quality_calibration_v9_statements={len(statements)}")
    print("memory_quality_calibration_v9_apply=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
