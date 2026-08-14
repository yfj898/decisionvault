from __future__ import annotations

import argparse
import os
from uuid import uuid4

from decisionvault.agent.engine import DecisionAgent
from decisionvault.agent.memory_governance import (
    PRODUCTION_SEMANTIC_MIN_SIMILARITY,
    ConflictAwareMemoryResolver,
)
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Outcome, Strategy
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import (
    NvidiaSemanticEmbedder,
    deterministic_text_embedding,
)
from decisionvault.memory.inmemory import InMemoryEpisodeStore


FIRST_CASE = (
    "customer payment failed twice after replacing their card and the saved "
    "payment token may be stale"
)
SIMILAR_CASE = (
    "payment failed again after card replacement; the stored token appears stale"
)
SEMANTIC_PARAPHRASE_CASE = (
    "customer cannot complete payment after getting a replacement card; "
    "the old authorization credential likely needs renewal"
)


def _delete_scope(connection_factory, scope_id: str) -> None:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM decision_memory_heads WHERE scope_id IN (%s, %s)",
                (scope_id, f"{scope_id}-isolated"),
            )
            cur.execute(
                "DELETE FROM decision_episodes WHERE scope_id IN (%s, %s)",
                (scope_id, f"{scope_id}-isolated"),
            )
        conn.commit()
    finally:
        conn.close()


def _run(
    store,
    scope_id: str,
    *,
    similar_case: str = SIMILAR_CASE,
    semantic: bool = False,
) -> None:
    policy = (
        OutcomeAwarePolicy(
            resolver=ConflictAwareMemoryResolver(
                minimum_similarity=PRODUCTION_SEMANTIC_MIN_SIMILARITY
            )
        )
        if semantic
        else OutcomeAwarePolicy()
    )
    producer = DecisionAgent(
        memory=store,
        agent_id="recovery-observer",
        policy=policy,
    )
    first = producer.decide(scope_id=scope_id, situation=FIRST_CASE)
    episode = producer.record_outcome(
        scope_id=scope_id,
        situation=FIRST_CASE,
        decision=first,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
        confidence=1.0,
    )

    consumer = DecisionAgent(
        memory=store,
        agent_id="recovery-planner",
        policy=policy,
    )
    shared = consumer.decide(scope_id=scope_id, situation=similar_case)
    isolated = consumer.decide(
        scope_id=f"{scope_id}-isolated",
        situation=similar_case,
    )

    producer_id = episode.evidence.get("producer_agent_id")
    print(f"producer_agent_id={producer_id}")
    print("consumer_agent_id=recovery-planner")
    print(f"shared_strategy={shared.strategy.value}")
    print(f"shared_memory_influenced={shared.memory_influenced}")
    print(
        "shared_recalled_producer_agent_ids="
        + ",".join(shared.recalled_producer_agent_ids)
    )
    print(f"isolated_strategy={isolated.strategy.value}")
    print(f"isolated_memory_influenced={isolated.memory_influenced}")

    if producer_id != "recovery-observer":
        raise RuntimeError("producer provenance missing")
    if shared.strategy != Strategy.REFRESH_PAYMENT_TOKEN:
        raise RuntimeError("consumer did not use producer outcome memory")
    if shared.recalled_producer_agent_ids != ("recovery-observer",):
        raise RuntimeError("consumer did not receive producer provenance")
    if isolated.strategy != Strategy.GENERIC_RETRY or isolated.memory_influenced:
        raise RuntimeError("scope isolation failed")
    print("shared_agent_memory_smoke=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("local", "cloud"), default="local")
    parser.add_argument("--semantic", action="store_true")
    args = parser.parse_args()

    scope_id = f"shared-memory-{uuid4()}"
    if args.backend == "local":
        _run(InMemoryEpisodeStore(), scope_id)
        return 0

    connection_factory = psycopg_connection_factory()
    if args.semantic:
        api_key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not api_key:
            raise SystemExit("NVIDIA_API_KEY is required for --semantic")
        semantic = NvidiaSemanticEmbedder(
            api_key=api_key,
            base_url=os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ),
            model_id=os.getenv(
                "NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"
            ),
        )
        store = CockroachVectorMemoryStore(
            connection_factory=connection_factory,
            embedder=deterministic_text_embedding,
            semantic_embedder=semantic.embed_passage,
            semantic_query_embedder=semantic.embed_query,
        )
        similar_case = SEMANTIC_PARAPHRASE_CASE
    else:
        store = CockroachVectorMemoryStore(
            connection_factory=connection_factory,
            embedder=deterministic_text_embedding,
        )
        similar_case = SIMILAR_CASE
    _delete_scope(connection_factory, scope_id)
    try:
        _run(
            store,
            scope_id,
            similar_case=similar_case,
            semantic=args.semantic,
        )
    finally:
        _delete_scope(connection_factory, scope_id)
    print("cloud_shared_memory_rows_cleaned=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
