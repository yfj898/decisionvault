from __future__ import annotations

import argparse
from pathlib import Path
import sys
from uuid import uuid4

from decisionvault.agent.engine import DecisionAgent
from decisionvault.domain import Outcome, Strategy
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import deterministic_text_embedding


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_SQL = ROOT / "scripts" / "bootstrap.sql"
FIRST_CASE = (
    "customer payment failed twice after replacing their card "
    "and the stored payment token may be stale"
)
SIMILAR_CASE = (
    "payment failed again after the customer replaced the card; "
    "the saved token looks stale"
)


def bootstrap(connection_factory) -> None:
    sql = BOOTSTRAP_SQL.read_text(encoding="utf-8")
    sql_without_comments = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [
        statement.strip()
        for statement in sql_without_comments.split(";")
        if statement.strip()
    ]
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
        conn.commit()
    finally:
        conn.close()


def delete_scope(connection_factory, scope_id: str) -> None:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM decision_episodes WHERE scope_id = %s",
                (scope_id,),
            )
        conn.commit()
    finally:
        conn.close()


def count_scope(connection_factory, scope_id: str) -> int:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM decision_episodes WHERE scope_id = %s",
                (scope_id,),
            )
            return int(cur.fetchone()[0])
    finally:
        conn.close()


def make_store(connection_factory) -> CockroachVectorMemoryStore:
    return CockroachVectorMemoryStore(
        connection_factory=connection_factory,
        embedder=deterministic_text_embedding,
    )


def seed(connection_factory, scope_id: str) -> str:
    agent = DecisionAgent(memory=make_store(connection_factory))
    decision = agent.decide(scope_id=scope_id, situation=FIRST_CASE)
    if decision.strategy != Strategy.GENERIC_RETRY or decision.memory_influenced:
        raise RuntimeError("seed precondition failed: scope already has influencing memory")
    episode = agent.record_outcome(
        scope_id=scope_id,
        situation=FIRST_CASE,
        decision=decision,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
    )
    print(f"seed_scope={scope_id}")
    print(f"seed_episode={episode.episode_id}")
    print(f"seed_strategy={decision.strategy.value}")
    print(f"rows_after_seed={count_scope(connection_factory, scope_id)}")
    return episode.episode_id


def recall(connection_factory, scope_id: str) -> None:
    # New store + new agent: no in-process episode state is reused.
    agent = DecisionAgent(memory=make_store(connection_factory))
    decision = agent.decide(scope_id=scope_id, situation=SIMILAR_CASE)
    baseline = DecisionAgent(
        memory=make_store(connection_factory),
        memory_enabled=False,
    ).decide(scope_id=scope_id, situation=SIMILAR_CASE)

    print(f"recall_scope={scope_id}")
    print(f"memory_on_strategy={decision.strategy.value}")
    print(f"memory_on_influenced={decision.memory_influenced}")
    print(f"recalled_episode_ids={','.join(decision.recalled_episode_ids)}")
    print(f"memory_off_strategy={baseline.strategy.value}")
    print(f"memory_off_influenced={baseline.memory_influenced}")

    if decision.strategy != Strategy.REFRESH_PAYMENT_TOKEN:
        raise RuntimeError("Cloud memory did not change the strategy")
    if not decision.memory_influenced or not decision.recalled_episode_ids:
        raise RuntimeError("Cloud recall did not provide causal episode evidence")
    if baseline.strategy != Strategy.GENERIC_RETRY or baseline.memory_influenced:
        raise RuntimeError("memory-off baseline is invalid")


def run(connection_factory, scope_id: str, keep: bool) -> None:
    bootstrap(connection_factory)
    delete_scope(connection_factory, scope_id)
    try:
        seed(connection_factory, scope_id)
        recall(connection_factory, scope_id)
        print("cloud_persistence_smoke=PASS")
    finally:
        if not keep:
            delete_scope(connection_factory, scope_id)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DecisionVault CockroachDB Cloud persistence smoke test"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=("run", "bootstrap", "seed", "recall", "cleanup"),
        default="run",
    )
    parser.add_argument("--scope", default=f"phase2-smoke-{uuid4()}")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    try:
        factory = psycopg_connection_factory()
        if args.command == "run":
            run(factory, args.scope, args.keep)
        elif args.command == "bootstrap":
            bootstrap(factory)
            print("bootstrap=PASS")
        elif args.command == "seed":
            bootstrap(factory)
            seed(factory, args.scope)
        elif args.command == "recall":
            recall(factory, args.scope)
        else:
            delete_scope(factory, args.scope)
            print(f"cleaned_scope={args.scope}")
    except Exception as exc:
        print(f"cloud_persistence_smoke=FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
