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
        description=(
            "Apply the governed adaptive-memory v7 expand and/or contract phase "
            "one statement per CockroachDB transaction."
        )
    )
    parser.add_argument("--database-url-file", type=Path, required=True)
    parser.add_argument("--ca-file", type=Path, required=True)
    parser.add_argument(
        "--phase",
        choices=("expand", "contract", "all"),
        default="all",
        help=(
            "Use expand before deploying the v7 Lambda. Apply contract only "
            "after readiness confirms a distinct consolidator identity."
        ),
    )
    args = parser.parse_args()

    import psycopg
    from psycopg.conninfo import conninfo_to_dict

    cfg = conninfo_to_dict(args.database_url_file.read_text(encoding="utf-8").strip())
    cfg["sslrootcert"] = str(args.ca_file.resolve())
    cfg["connect_timeout"] = "5"
    cfg["options"] = "-c statement_timeout=120000"
    phase_files = {
        "expand": ("governed_adaptive_memory_v7_expand.sql",),
        "contract": ("governed_adaptive_memory_v7_contract.sql",),
        "all": (
            "governed_adaptive_memory_v7_expand.sql",
            "governed_adaptive_memory_v7_contract.sql",
        ),
    }
    statements: list[str] = []
    for filename in phase_files[args.phase]:
        statements.extend(
            _statements(
                (ROOT / "scripts" / filename).read_text(encoding="utf-8")
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
                        "governed_adaptive_memory_v7_"
                        f"{args.phase}_statement_{index}=FAIL:{type(exc).__name__}"
                    )
                    return 2
    finally:
        conn.close()

    print(f"governed_adaptive_memory_v7_phase={args.phase}")
    print(f"governed_adaptive_memory_v7_statements={len(statements)}")
    print(f"governed_adaptive_memory_v7_{args.phase}_apply=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
