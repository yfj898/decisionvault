from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

from decisionvault.memory.cockroach import _vector_literal
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import deterministic_text_embedding


ROOT = Path(__file__).resolve().parents[1]
VECTOR_INDEX_SQL = ROOT / "scripts" / "vector_index.sql"
INDEX_NAME = "decision_episodes_scope_embedding_vec_idx"

QUERY = (
    "payment failed again after the customer replaced the card; "
    "the saved token looks stale"
)
TARGET = (
    "customer payment failed twice after replacing their card "
    "and the stored payment token may be stale"
)

DISTRACTOR_WORDS = (
    "warehouse",
    "inventory",
    "shipment",
    "forecast",
    "garden",
    "camera",
    "printer",
    "network",
    "invoice",
    "meeting",
    "calendar",
    "weather",
    "package",
    "router",
    "sensor",
    "document",
    "backup",
    "report",
    "analytics",
    "catalog",
    "product",
    "delivery",
    "location",
    "device",
    "accounting",
    "archive",
    "monitor",
    "dashboard",
    "schedule",
    "storage",
)


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _index_exists(connection_factory) -> bool:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW INDEXES FROM decision_episodes")
            return any(row[1] == INDEX_NAME for row in cur.fetchall())
    finally:
        conn.close()


def ensure_index(connection_factory) -> None:
    if _index_exists(connection_factory):
        print("vector_index_create=SKIP_ALREADY_EXISTS")
        return

    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(VECTOR_INDEX_SQL.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()

    if not _index_exists(connection_factory):
        raise RuntimeError("vector index was not visible after CREATE VECTOR INDEX")
    print("vector_index_create=PASS")


def _distractors(count: int) -> list[tuple[str, list[float]]]:
    query_vector = deterministic_text_embedding(QUERY)
    result: list[tuple[str, list[float]]] = []
    candidate = 0
    while len(result) < count:
        first = DISTRACTOR_WORDS[candidate % len(DISTRACTOR_WORDS)]
        second = DISTRACTOR_WORDS[(candidate * 7 + 3) % len(DISTRACTOR_WORDS)]
        third = DISTRACTOR_WORDS[(candidate * 11 + 5) % len(DISTRACTOR_WORDS)]
        text = (
            f"{first} {second} {third} reference item {1000 + candidate} "
            "routine status review"
        )
        vector = deterministic_text_embedding(text)
        if _cosine(query_vector, vector) < 0.25:
            result.append((text, vector))
        candidate += 1
    return result


def _delete_scopes(connection_factory, *scope_ids: str) -> None:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM decision_episodes WHERE scope_id = ANY(%s)",
                (list(scope_ids),),
            )
        conn.commit()
    finally:
        conn.close()


def run(connection_factory, *, distractor_count: int = 192) -> None:
    ensure_index(connection_factory)

    scope_id = f"phase3-ann-{uuid4().hex[:12]}"
    foreign_scope_id = f"{scope_id}-foreign"
    target_episode_id = str(uuid4())
    foreign_episode_id = str(uuid4())
    query_vector = deterministic_text_embedding(QUERY)
    query_literal = _vector_literal(query_vector)
    now = datetime.now(timezone.utc)

    insert_sql = """
        INSERT INTO decision_episodes (
            episode_id, scope_id, situation, strategy, outcome,
            effectiveness, confidence, evidence, embedding, created_at
        )
        VALUES (
            %s::UUID, %s, %s, %s, %s,
            %s, %s, %s::JSONB, %s::VECTOR, %s
        )
    """

    _delete_scopes(connection_factory, scope_id, foreign_scope_id)
    try:
        conn = connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    insert_sql,
                    (
                        target_episode_id,
                        scope_id,
                        TARGET,
                        "GENERIC_RETRY",
                        "FAILED",
                        0.1,
                        1.0,
                        json.dumps({"kind": "phase3-target"}),
                        _vector_literal(deterministic_text_embedding(TARGET)),
                        now,
                    ),
                )

                for number, (situation, vector) in enumerate(
                    _distractors(distractor_count)
                ):
                    cur.execute(
                        insert_sql,
                        (
                            str(uuid4()),
                            scope_id,
                            situation,
                            "VERIFY_BILLING_PROFILE",
                            "UNKNOWN",
                            0.5,
                            0.5,
                            json.dumps(
                                {"kind": "phase3-distractor", "number": number}
                            ),
                            _vector_literal(vector),
                            now,
                        ),
                    )

                # This row is a perfect vector match but belongs to another scope.
                # A correct prefix-column index must not leak it into the query.
                cur.execute(
                    insert_sql,
                    (
                        foreign_episode_id,
                        foreign_scope_id,
                        QUERY,
                        "VERIFY_BILLING_PROFILE",
                        "SUCCESS",
                        1.0,
                        1.0,
                        json.dumps({"kind": "phase3-foreign-perfect-match"}),
                        query_literal,
                        now,
                    ),
                )
            conn.commit()
        finally:
            conn.close()

        ann_sql = """
            SELECT episode_id::STRING, embedding <=> %s::VECTOR AS distance
            FROM decision_episodes
            WHERE scope_id = %s
            ORDER BY embedding <=> %s::VECTOR
            LIMIT 5
        """
        exact_sql = """
            SELECT episode_id::STRING, embedding <=> %s::VECTOR AS distance
            FROM decision_episodes@decision_episodes_pkey
            WHERE scope_id = %s
            ORDER BY embedding <=> %s::VECTOR
            LIMIT 5
        """

        conn = connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM decision_episodes WHERE scope_id = %s",
                    (scope_id,),
                )
                same_scope_rows = int(cur.fetchone()[0])

                cur.execute(ann_sql, (query_literal, scope_id, query_literal))
                ann = cur.fetchall()
                cur.execute(exact_sql, (query_literal, scope_id, query_literal))
                exact = cur.fetchall()

                ann_ids = [row[0] for row in ann]
                exact_ids = [row[0] for row in exact]
                recall_at_5 = len(set(ann_ids) & set(exact_ids)) / 5

                cur.execute(
                    "EXPLAIN " + ann_sql,
                    (query_literal, scope_id, query_literal),
                )
                ann_plan = "\n".join(row[0] for row in cur.fetchall())
                cur.execute(
                    "EXPLAIN " + exact_sql,
                    (query_literal, scope_id, query_literal),
                )
                exact_plan = "\n".join(row[0] for row in cur.fetchall())
        finally:
            conn.close()

        checks = {
            "ann_top1_is_target": ann_ids[0] == target_episode_id,
            "exact_top1_is_target": exact_ids[0] == target_episode_id,
            "foreign_perfect_match_excluded": foreign_episode_id not in ann_ids,
            "ann_plan_vector_search": "vector search" in ann_plan.lower(),
            "ann_plan_vector_index": INDEX_NAME in ann_plan,
            "exact_plan_vector_search": "vector search" in exact_plan.lower(),
            "exact_plan_primary_index": "decision_episodes_pkey" in exact_plan,
        }

        print(f"same_scope_rows={same_scope_rows}")
        print(f"ann_top1_distance={float(ann[0][1]):.6f}")
        print(f"exact_top1_distance={float(exact[0][1]):.6f}")
        print(f"recall_at_5={recall_at_5:.3f}")
        for name, value in checks.items():
            print(f"{name}={value}")

        if not all(
            (
                checks["ann_top1_is_target"],
                checks["exact_top1_is_target"],
                checks["foreign_perfect_match_excluded"],
                checks["ann_plan_vector_search"],
                checks["ann_plan_vector_index"],
                not checks["exact_plan_vector_search"],
                checks["exact_plan_primary_index"],
                recall_at_5 == 1.0,
            )
        ):
            raise RuntimeError("distributed vector index verification failed")

        print("phase3_vector_index_smoke=PASS")
    finally:
        _delete_scopes(connection_factory, scope_id, foreign_scope_id)
        conn = connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM decision_episodes WHERE scope_id = ANY(%s)",
                    ([scope_id, foreign_scope_id],),
                )
                print(f"rows_after_cleanup={int(cur.fetchone()[0])}")
        finally:
            conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify CockroachDB Distributed Vector Index behavior"
    )
    parser.add_argument("--distractors", type=int, default=192)
    args = parser.parse_args()
    if args.distractors < 5:
        parser.error("--distractors must be at least 5")

    factory = psycopg_connection_factory()
    run(factory, distractor_count=args.distractors)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
