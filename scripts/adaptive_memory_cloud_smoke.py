from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import os
from threading import Barrier
from uuid import uuid4

from decisionvault.adaptive_memory import (
    ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
    MemoryScopeLevel,
    derive_context_tags,
)
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import DecisionEpisode, Outcome, Strategy
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.consolidation import CockroachMemoryConsolidationService
from decisionvault.memory.embedding import NvidiaSemanticEmbedder, deterministic_text_embedding
from decisionvault.memory.retry import retry_cockroach_serialization


ADAPTIVE_CLOUD_TEST_PREFIX = "adaptive-cloud-"


def _delete_prefix(connection_factory, prefix: str) -> None:
    def operation() -> None:
        conn = connection_factory()
        try:
            with conn.cursor() as cur:
                # Delete authoritative L1 first so a concurrent consolidator
                # must serialize against the evidence removal before derived
                # projection cleanup completes.
                cur.execute(
                    "DELETE FROM decision_memory_heads WHERE scope_id LIKE %s",
                    (f"{prefix}%",),
                )
                cur.execute(
                    "DELETE FROM decision_episodes WHERE scope_id LIKE %s",
                    (f"{prefix}%",),
                )
                cur.execute(
                    "DELETE FROM decision_memory_consolidation_outbox WHERE scope_id LIKE %s",
                    (f"{prefix}%",),
                )
                cur.execute(
                    """
                    DELETE FROM decision_governed_memory_support
                    WHERE memory_id IN (
                        SELECT memory_id FROM decision_governed_memories
                        WHERE scope_id LIKE %s
                    )
                    """,
                    (f"{prefix}%",),
                )
                cur.execute(
                    "DELETE FROM decision_governed_memories WHERE scope_id LIKE %s",
                    (f"{prefix}%",),
                )
                cur.execute(
                    "DELETE FROM decision_memory_consolidation_candidates WHERE scope_id LIKE %s",
                    (f"{prefix}%",),
                )
                cur.execute(
                    "DELETE FROM decision_strategy_effectiveness WHERE scope_id LIKE %s",
                    (f"{prefix}%",),
                )
                cur.execute(
                    "DELETE FROM decision_memory_revocations WHERE scope_id LIKE %s",
                    (f"{prefix}%",),
                )
            conn.commit()
        except Exception:
            rollback = getattr(conn, "rollback", None)
            if callable(rollback):
                rollback()
            raise
        finally:
            conn.close()

    retry_cockroach_serialization(operation, max_attempts=5)


def _remaining_rows(connection_factory, prefix: str) -> dict[str, int]:
    tables = (
        "decision_memory_consolidation_outbox",
        "decision_memory_consolidation_candidates",
        "decision_strategy_effectiveness",
        "decision_governed_memories",
        "decision_memory_revocations",
        "decision_memory_heads",
        "decision_episodes",
    )
    conn = connection_factory()
    try:
        result: dict[str, int] = {}
        with conn.cursor() as cur:
            for table in tables:
                cur.execute(
                    f"SELECT count(*) FROM {table} WHERE scope_id LIKE %s",
                    (f"{prefix}%",),
                )
                result[table] = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT count(*)
                FROM decision_governed_memory_support s
                JOIN decision_governed_memories m ON m.memory_id = s.memory_id
                WHERE m.scope_id LIKE %s
                """,
                (f"{prefix}%",),
            )
            result["decision_governed_memory_support"] = int(cur.fetchone()[0])
        return result
    finally:
        conn.close()


def _invalid_active_support_count(connection_factory, scope_id: str) -> int:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT count(*)
                FROM decision_governed_memories m
                WHERE m.scope_id = %s
                  AND m.status = 'ACTIVE'
                  AND EXISTS (
                    SELECT 1
                    FROM decision_governed_memory_support s
                    WHERE s.memory_id = m.memory_id
                      AND NOT EXISTS (
                        SELECT 1
                        FROM decision_memory_heads h
                        WHERE h.scope_id = m.scope_id
                          AND h.episode_id = s.episode_id
                          AND h.semantic_embedding_space = m.semantic_embedding_space
                      )
                  )
                """,
                (scope_id,),
            )
            return int(cur.fetchone()[0])
    finally:
        conn.close()


def _episode(
    *,
    scope_id: str,
    producer: str,
    outcome: Outcome,
    observed_at: datetime,
    episode_id: str | None = None,
    supersedes_episode_id: str | None = None,
) -> DecisionEpisode:
    evidence = {
        "producer_agent_id": producer,
        "situation_class": "stale_payment_token",
        "preconditions": "card_replaced,stale_token",
        "exclusions": "insufficient_funds,account_blocked",
        "memory_status": "ACTIVE",
    }
    if supersedes_episode_id:
        evidence["supersedes_episode_id"] = supersedes_episode_id
    return DecisionEpisode(
        episode_id=episode_id or str(uuid4()),
        scope_id=scope_id,
        situation="replacement card still uses an old stored payment credential",
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
        outcome=outcome,
        effectiveness=0.95 if outcome == Outcome.SUCCESS else 0.05,
        confidence=1.0,
        evidence=evidence,
        observed_at=observed_at,
        recorded_at=datetime.now(timezone.utc),
    )


def _seed_pair(store: CockroachVectorMemoryStore, scope_id: str) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    first = _episode(
        scope_id=scope_id,
        producer="adaptive-agent-a",
        outcome=Outcome.SUCCESS,
        observed_at=now,
    )
    second = _episode(
        scope_id=scope_id,
        producer="adaptive-agent-b",
        outcome=Outcome.SUCCESS,
        observed_at=now + timedelta(milliseconds=1),
    )
    store.save(first)
    store.save(second)
    return first.episode_id, second.episode_id


def _race(
    *,
    service: CockroachMemoryConsolidationService,
    scope_id: str,
    mutation,
) -> None:
    barrier = Barrier(2)

    def consolidate():
        barrier.wait()
        return service.consolidate_scope(
            scope_id=scope_id,
            scope_level=MemoryScopeLevel.TEAM,
            active_producer_agent_ids={"adaptive-agent-a", "adaptive-agent-b"},
        )

    def mutate():
        barrier.wait()
        return mutation()

    with ThreadPoolExecutor(max_workers=2) as pool:
        left = pool.submit(consolidate)
        right = pool.submit(mutate)
        left.result(timeout=30)
        right.result(timeout=30)


def main() -> int:
    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    revision = os.getenv("NVIDIA_EMBED_REVISION", "").strip()
    runtime_database_url = os.getenv("DATABASE_URL", "").strip()
    consolidation_database_url = os.getenv(
        "CONSOLIDATION_DATABASE_URL", runtime_database_url
    ).strip()
    cleanup_database_url = os.getenv(
        "DECISIONVAULT_CLEANUP_DATABASE_URL", runtime_database_url
    ).strip()
    if not runtime_database_url:
        raise SystemExit("DATABASE_URL is required")
    if not consolidation_database_url:
        raise SystemExit("CONSOLIDATION_DATABASE_URL is required")
    if not cleanup_database_url:
        raise SystemExit("DECISIONVAULT_CLEANUP_DATABASE_URL is required")
    if not api_key:
        raise SystemExit("NVIDIA_API_KEY is required")
    if not revision:
        raise SystemExit("NVIDIA_EMBED_REVISION is required")

    connection_factory = psycopg_connection_factory(
        runtime_database_url,
        statement_timeout_ms=20000,
    )
    # v7 deliberately splits adaptive authority from the request runtime:
    # runtime writes L1/current heads and invalidates stale L3, while the
    # consolidator owns candidate/L2/L3 promotion writes. Keep the cloud smoke
    # on that same production boundary instead of widening runtime privileges.
    consolidation_connection_factory = psycopg_connection_factory(
        consolidation_database_url,
        statement_timeout_ms=20000,
    )
    # Production business operations deliberately use the least-privilege
    # runtime identity. Test cleanup may require DELETE on append-only audit
    # tables that the runtime identity must never receive, so cleanup can use a
    # separate migration-admin URL without widening production privileges.
    cleanup_connection_factory = psycopg_connection_factory(
        cleanup_database_url,
        statement_timeout_ms=20000,
    )
    semantic = NvidiaSemanticEmbedder(
        api_key=api_key,
        revision=revision,
        model_id=os.getenv("NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"),
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        timeout_seconds=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20")),
    )
    store = CockroachVectorMemoryStore(
        connection_factory=connection_factory,
        embedder=deterministic_text_embedding,
        semantic_embedder=semantic.embed_passage,
        semantic_query_embedder=semantic.embed_query,
        semantic_embedding_space=semantic.embedding_space,
    )
    service = CockroachMemoryConsolidationService(
        connection_factory=consolidation_connection_factory,
        semantic_embedder=semantic.embed_passage,
        semantic_embedding_space=semantic.embedding_space,
    )
    prefix = f"{ADAPTIVE_CLOUD_TEST_PREFIX}{uuid4().hex[:10]}"
    checks: dict[str, bool] = {}
    exit_code = 2
    cleanup_ok = False
    # This namespace is reserved for this real-cloud smoke. Clean abandoned
    # prefixes from a prior interrupted/serialization-aborted run before
    # starting a new one so one failed test cannot pollute later global audits.
    _delete_prefix(cleanup_connection_factory, ADAPTIVE_CLOUD_TEST_PREFIX)
    try:
        positive_scope = f"{prefix}-positive"
        _seed_pair(store, positive_scope)
        promoted = service.consolidate_scope(
            scope_id=positive_scope,
            active_producer_agent_ids={"adaptive-agent-a", "adaptive-agent-b"},
        )
        memories = store.recall_adaptive(
            scope_id=positive_scope,
            situation="replacement card checkout still uses a stale token",
            minimum_similarity=0.40,
        )
        decision = OutcomeAwarePolicy().decide(
            recalled=[],
            adaptive_memories=memories,
            context_tags=set(
                derive_context_tags(
                    "replacement card checkout still uses a stale token"
                )
            ),
        )
        checks["team_promotion"] = promoted.promoted_count == 1
        checks["adaptive_retrieval"] = bool(memories)
        checks["adaptive_decision"] = (
            decision.strategy == Strategy.REFRESH_PAYMENT_TOKEN
            and decision.memory_resolution == "GOVERNED_ADAPTIVE_MEMORY"
            and bool(decision.recalled_memory_ids)
        )

        crowd_scope = f"{prefix}-crowd"
        base = datetime.now(timezone.utc)
        for index in range(4):
            store.save(
                _episode(
                    scope_id=crowd_scope,
                    producer="adaptive-agent-a",
                    outcome=Outcome.SUCCESS,
                    observed_at=base + timedelta(milliseconds=index),
                )
            )
        crowded = service.consolidate_scope(
            scope_id=crowd_scope,
            active_producer_agent_ids={"adaptive-agent-a"},
        )
        checks["producer_crowding_blocked"] = crowded.promoted_count == 0

        contradiction_scope = f"{prefix}-contradiction"
        now = datetime.now(timezone.utc)
        for index in range(3):
            store.save(
                _episode(
                    scope_id=contradiction_scope,
                    producer=f"success-{index}",
                    outcome=Outcome.SUCCESS,
                    observed_at=now + timedelta(milliseconds=index),
                )
            )
        store.save(
            _episode(
                scope_id=contradiction_scope,
                producer="failure-independent",
                outcome=Outcome.FAILED,
                observed_at=now + timedelta(milliseconds=4),
            )
        )
        contradiction = service.consolidate_scope(
            scope_id=contradiction_scope,
            active_producer_agent_ids={
                "success-0",
                "success-1",
                "success-2",
                "failure-independent",
            },
        )
        checks["independent_contradiction_abstains"] = (
            contradiction.promoted_count == 0
            and "CONTRADICTION_ABSTAIN" in contradiction.resolutions
        )

        post_promotion_scope = f"{prefix}-post-promotion-contradiction"
        _seed_pair(store, post_promotion_scope)
        initial = service.consolidate_scope(
            scope_id=post_promotion_scope,
            active_producer_agent_ids={"adaptive-agent-a", "adaptive-agent-b"},
        )
        store.save(
            _episode(
                scope_id=post_promotion_scope,
                producer="adaptive-agent-c",
                outcome=Outcome.FAILED,
                observed_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            )
        )
        conflicted = service.consolidate_scope(
            scope_id=post_promotion_scope,
            active_producer_agent_ids={
                "adaptive-agent-a",
                "adaptive-agent-b",
                "adaptive-agent-c",
            },
        )
        post_conflict_memories = store.recall_adaptive(
            scope_id=post_promotion_scope,
            situation="replacement card checkout still uses a stale token",
            minimum_similarity=0.40,
        )
        checks["contradiction_revokes_prior_l3"] = (
            initial.promoted_count == 1
            and "CONTRADICTION_ABSTAIN" in conflicted.resolutions
            and not post_conflict_memories
        )

        negative_scope = f"{prefix}-negative"
        now = datetime.now(timezone.utc)
        for index in range(2):
            store.save(
                _episode(
                    scope_id=negative_scope,
                    producer=f"negative-{index}",
                    outcome=Outcome.FAILED,
                    observed_at=now + timedelta(milliseconds=index),
                )
            )
        negative = service.consolidate_scope(
            scope_id=negative_scope,
            active_producer_agent_ids={"negative-0", "negative-1"},
        )
        negative_memories = store.recall_adaptive(
            scope_id=negative_scope,
            situation="replacement card still uses a stale token",
            minimum_similarity=0.40,
        )
        negative_decision = OutcomeAwarePolicy().decide(
            recalled=[],
            adaptive_memories=negative_memories,
            context_tags={"card_replaced", "stale_token"},
        )
        checks["negative_promoted"] = negative.promoted_count == 1
        checks["negative_veto"] = (
            Strategy.REFRESH_PAYMENT_TOKEN.value
            in negative_decision.governance_trace.vetoed_strategies
        )

        mismatch_scope = f"{prefix}-revision"
        _seed_pair(store, mismatch_scope)
        conn = connection_factory()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE decision_memory_heads
                    SET semantic_embedding_space = %s
                    WHERE scope_id = %s AND producer_agent_id = %s
                    """,
                    (
                        "nvidia/nv-embedqa-e5-v5|revision=foreign-test|dim=1024|contract=query-passage-v1",
                        mismatch_scope,
                        "adaptive-agent-b",
                    ),
                )
            conn.commit()
        finally:
            conn.close()
        mismatch = service.consolidate_scope(
            scope_id=mismatch_scope,
            active_producer_agent_ids={"adaptive-agent-a", "adaptive-agent-b"},
        )
        checks["cross_revision_blocked"] = (
            mismatch.promoted_count == 0
            and "EMBEDDING_REVISION_MISMATCH" in mismatch.resolutions
        )

        normal_scope = f"{prefix}-race-normal"
        _seed_pair(store, normal_scope)
        service.consolidate_scope(
            scope_id=normal_scope,
            active_producer_agent_ids={"adaptive-agent-a", "adaptive-agent-b"},
        )
        _race(
            service=service,
            scope_id=normal_scope,
            mutation=lambda: store.save(
                _episode(
                    scope_id=normal_scope,
                    producer="adaptive-agent-a",
                    outcome=Outcome.FAILED,
                    observed_at=datetime.now(timezone.utc) + timedelta(seconds=2),
                )
            ),
        )
        checks["consolidation_vs_normal_write"] = (
            _invalid_active_support_count(connection_factory, normal_scope) == 0
        )

        supersede_scope = f"{prefix}-race-supersede"
        old_a, _ = _seed_pair(store, supersede_scope)
        service.consolidate_scope(
            scope_id=supersede_scope,
            active_producer_agent_ids={"adaptive-agent-a", "adaptive-agent-b"},
        )
        _race(
            service=service,
            scope_id=supersede_scope,
            mutation=lambda: store.save(
                _episode(
                    scope_id=supersede_scope,
                    producer="adaptive-agent-a",
                    outcome=Outcome.SUCCESS,
                    observed_at=datetime.now(timezone.utc) + timedelta(seconds=2),
                    supersedes_episode_id=old_a,
                )
            ),
        )
        checks["consolidation_vs_supersession"] = (
            _invalid_active_support_count(connection_factory, supersede_scope) == 0
        )

        revoke_scope = f"{prefix}-race-revoke"
        revoke_a, _ = _seed_pair(store, revoke_scope)
        service.consolidate_scope(
            scope_id=revoke_scope,
            active_producer_agent_ids={"adaptive-agent-a", "adaptive-agent-b"},
        )
        _race(
            service=service,
            scope_id=revoke_scope,
            mutation=lambda: store.revoke_current_head(
                scope_id=revoke_scope,
                producer_agent_id="adaptive-agent-a",
                episode_id=revoke_a,
                reason="adaptive cloud concurrency test",
            ),
        )
        checks["consolidation_vs_revocation"] = (
            _invalid_active_support_count(connection_factory, revoke_scope) == 0
        )

        checks["governance_revision"] = (
            ADAPTIVE_MEMORY_GOVERNANCE_REVISION == "governed-adaptive-memory-v1"
        )
        for name, passed in checks.items():
            print(f"{name}={'PASS' if passed else 'FAIL'}")
        passed_count = sum(checks.values())
        print(f"adaptive_cloud_checks={passed_count}/{len(checks)}")
        exit_code = 0 if passed_count == len(checks) else 2
    finally:
        _delete_prefix(cleanup_connection_factory, prefix)
        remaining = _remaining_rows(
            cleanup_connection_factory,
            ADAPTIVE_CLOUD_TEST_PREFIX,
        )
        cleanup_ok = all(value == 0 for value in remaining.values())
        print("adaptive_cloud_cleanup=" + ("PASS" if cleanup_ok else "FAIL"))
        print("adaptive_cloud_temporary_rows=" + str(sum(remaining.values())))
    return exit_code if cleanup_ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
