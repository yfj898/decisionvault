from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _statements(sql: str) -> list[str]:
    """Split this migration's simple DDL/DML file into committed statements."""

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
        description=(
            "Apply production_memory_v5.sql one statement per CockroachDB "
            "transaction so online schema changes are visible to later steps."
        )
    )
    parser.add_argument(
        "--database-url-file",
        type=Path,
        required=True,
        help="Path to a file containing the admin/migration database URL.",
    )
    parser.add_argument(
        "--ca-file",
        type=Path,
        required=True,
        help="Public CockroachDB Cloud root CA used for this connection.",
    )
    args = parser.parse_args()

    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    cfg = conninfo_to_dict(args.database_url_file.read_text(encoding="utf-8").strip())
    cfg["sslrootcert"] = str(args.ca_file.resolve())
    cfg["connect_timeout"] = "5"
    # Runtime SQL intentionally stays at 8 seconds. Online schema changes can
    # take longer even on empty tables, so the migration runner gets a separate
    # bounded two-minute DDL timeout rather than inheriting runtime latency SLOs.
    cfg["options"] = "-c statement_timeout=120000"
    statements = _statements(
        (ROOT / "scripts" / "production_memory_v5.sql").read_text(encoding="utf-8")
    )

    conn = psycopg.connect(**cfg, autocommit=True)
    try:
        with conn.cursor() as cur:
            for index, statement in enumerate(statements, start=1):
                try:
                    cur.execute(statement)
                except Exception as exc:
                    print(f"production_memory_v5_statement_{index}=FAIL:{type(exc).__name__}")
                    return 2
    finally:
        conn.close()

    print(f"production_memory_v5_statements={len(statements)}")
    print("production_memory_v5_apply=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
