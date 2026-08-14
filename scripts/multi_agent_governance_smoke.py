from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
from uuid import uuid4

from decisionvault.agent.engine import DecisionAgent
from decisionvault.agent.memory_governance import ConflictAwareMemoryResolver
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import DecisionEpisode, Outcome, Strategy
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import NvidiaSemanticEmbedder, deterministic_text_embedding


SITUATION = (
    "customer cannot complete payment after getting a replacement card; "
    "the old authorization credential likely needs renewal"
)


def _episode(
    *,
    scope_id: str,
    producer: str,
    strategy: Strategy,
    outcome: Outcome,
    effectiveness: float,
    age_days: float = 0.0,
    extra: dict[str, str] | None = None,
) -> DecisionEpisode:
    return DecisionEpisode(
        episode_id=str(uuid4()),
        scope_id=scope_id,
        situation=SITUATION,
        strategy=strategy,
        outcome=outcome,
        effectiveness=effectiveness,
        confidence=1.0,
        evidence={"producer_agent_id": producer, **(extra or {})},
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )


def _delete_prefix(connection_factory, prefix: str) -> None:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM decision_episodes WHERE scope_id LIKE %s",
                (f"{prefix}%",),
            )
        conn.commit()
    finally:
        conn.close()


def _build_store(connection_factory, *, semantic: bool):
    if not semantic:
        return CockroachVectorMemoryStore(
            connection_factory=connection_factory,
            embedder=deterministic_text_embedding,
        )
    key = os.getenv("NVIDIA_API_KEY", "").strip()
    if not key:
        raise SystemExit("NVIDIA_API_KEY is required for --semantic")
    embedder = NvidiaSemanticEmbedder(
        api_key=key,
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        model_id=os.getenv("NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"),
    )
    return CockroachVectorMemoryStore(
        connection_factory=connection_factory,
        embedder=embedder.embed_passage,
        query_embedder=embedder.embed_query,
    )


def _run(store, prefix: str) -> None:
    conflict_scope = f"{prefix}-conflict"
    store.save(
        _episode(
            scope_id=conflict_scope,
            producer="agent-a",
            strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            outcome=Outcome.SUCCESS,
            effectiveness=0.9,
        )
    )
    store.save(
        _episode(
            scope_id=conflict_scope,
            producer="agent-b",
            strategy=Strategy.REFRESH_PAYMENT_TOKEN,
            outcome=Outcome.FAILED,
            effectiveness=0.1,
        )
    )
    conflict = DecisionAgent(memory=store, agent_id="agent-c").decide(
        scope_id=conflict_scope,
        situation=SITUATION,
    )
    print(f"balanced_conflict_strategy={conflict.strategy.value}")
    print(f"balanced_conflict_influenced={conflict.memory_influenced}")
    print(f"balanced_conflict_resolution={conflict.memory_resolution}")
    if (
        conflict.strategy != Strategy.GENERIC_RETRY
        or conflict.memory_influenced
        or not conflict.memory_conflict
    ):
        raise RuntimeError("balanced contradiction did not abstain")

    trusted_policy = OutcomeAwarePolicy(
        resolver=ConflictAwareMemoryResolver(
            producer_trust={"agent-a": 1.0, "agent-b": 0.2}
        )
    )
    trusted = DecisionAgent(
        memory=store,
        agent_id="agent-c",
        policy=trusted_policy,
    ).decide(scope_id=conflict_scope, situation=SITUATION)
    print(f"trusted_resolution_strategy={trusted.strategy.value}")
    print(f"trusted_resolution_conflict={trusted.memory_conflict}")
    if trusted.strategy != Strategy.REFRESH_PAYMENT_TOKEN or not trusted.memory_influenced:
        raise RuntimeError("explicit trust registry did not resolve conflict")

    stale_scope = f"{prefix}-stale"
    store.save(
        _episode(
            scope_id=stale_scope,
            producer="agent-a",
            strategy=Strategy.VERIFY_BILLING_PROFILE,
            outcome=Outcome.SUCCESS,
            effectiveness=0.95,
            age_days=120,
        )
    )
    stale = DecisionAgent(memory=store, agent_id="agent-c").decide(
        scope_id=stale_scope,
        situation=SITUATION,
    )
    print(f"stale_strategy={stale.strategy.value}")
    print(f"stale_resolution={stale.memory_resolution}")
    if stale.strategy != Strategy.GENERIC_RETRY or stale.memory_influenced:
        raise RuntimeError("stale memory propagated")

    supersede_scope = f"{prefix}-supersede"
    old = _episode(
        scope_id=supersede_scope,
        producer="agent-a",
        strategy=Strategy.VERIFY_BILLING_PROFILE,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
        age_days=2,
    )
    store.save(old)
    new = _episode(
        scope_id=supersede_scope,
        producer="agent-a",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        outcome=Outcome.SUCCESS,
        effectiveness=0.95,
        age_days=1,
        extra={"supersedes_episode_id": old.episode_id},
    )
    store.save(new)
    superseded = DecisionAgent(memory=store, agent_id="agent-c").decide(
        scope_id=supersede_scope,
        situation=SITUATION,
    )
    print(f"supersession_strategy={superseded.strategy.value}")
    print("supersession_old_recalled=" + str(old.episode_id in superseded.recalled_episode_ids))
    if (
        superseded.strategy != Strategy.REFRESH_PAYMENT_TOKEN
        or old.episode_id in superseded.recalled_episode_ids
    ):
        raise RuntimeError("superseded memory still influenced decision")

    duplicate_scope = f"{prefix}-duplicate"
    for index in range(4):
        store.save(
            _episode(
                scope_id=duplicate_scope,
                producer="agent-a",
                strategy=Strategy.VERIFY_BILLING_PROFILE,
                outcome=Outcome.SUCCESS,
                effectiveness=0.9,
                age_days=(4 - index) / 10,
            )
        )
    store.save(
        _episode(
            scope_id=duplicate_scope,
            producer="agent-b",
            strategy=Strategy.VERIFY_BILLING_PROFILE,
            outcome=Outcome.FAILED,
            effectiveness=0.1,
        )
    )
    duplicate = DecisionAgent(memory=store, agent_id="agent-c").decide(
        scope_id=duplicate_scope,
        situation=SITUATION,
    )
    print(f"duplicate_vote_strategy={duplicate.strategy.value}")
    print(f"duplicate_vote_conflict={duplicate.memory_conflict}")
    if duplicate.strategy != Strategy.GENERIC_RETRY or not duplicate.memory_conflict:
        raise RuntimeError("duplicate producer writes amplified one producer's vote")

    print("multi_agent_governance_smoke=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--semantic", action="store_true")
    args = parser.parse_args()

    connection_factory = psycopg_connection_factory()
    store = _build_store(connection_factory, semantic=args.semantic)
    prefix = f"governance-{uuid4()}"
    _delete_prefix(connection_factory, prefix)
    try:
        _run(store, prefix)
    finally:
        _delete_prefix(connection_factory, prefix)
    print("governance_cloud_rows_cleaned=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
