from __future__ import annotations

import base64
from dataclasses import asdict
import hmac
import json
import os
import time
from typing import Any
from uuid import UUID, uuid4

from decisionvault.adaptive_memory import (
    ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
    MemoryScopeLevel,
    derive_context_tags,
)
from decisionvault.agent.engine import DecisionAgent
from decisionvault.agent.auth import AgentGrant, authenticate_agent, load_agent_grants
from decisionvault.agent.memory_governance import (
    PRODUCTION_SEMANTIC_MIN_SIMILARITY,
    ConflictAwareMemoryResolver,
)
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Decision, DecisionAction, Outcome, Strategy
from decisionvault.execution import (
    DecisionSnapshotStale,
    configured_sandbox_scenario,
    decision_provenance_payload,
    decision_state_digest,
    issue_decision_snapshot,
    issue_sandbox_receipt,
    verify_decision_snapshot,
    verify_execution_receipt,
)
from decisionvault.memory.cockroach import (
    CockroachVectorMemoryStore,
    MemoryRevocationConflict,
    SupersessionWriteConflict,
)
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.consolidation import CockroachMemoryConsolidationService
from decisionvault.memory.embedding import (
    NvidiaSemanticEmbedder,
    deterministic_text_embedding,
    semantic_embedding_space,
)
from decisionvault.observability import emit_request_metric
from decisionvault.providers.nvidia import NvidiaDecisionAdvisor
from decisionvault.providers.http_security import validate_nvidia_base_url
from decisionvault.rate_limit import CockroachRateLimiter
from decisionvault.runtime_secrets import hydrate_runtime_secrets
from decisionvault.ui import INDEX_HTML


DEMO_FIRST_CASE = (
    "customer payment failed twice after replacing their card "
    "and the stored payment token may be stale"
)
DEMO_SIMILAR_CASE = (
    "payment failed again after the customer replaced the card; "
    "the saved token looks stale"
)
GOVERNANCE_CONFLICT_CASE = (
    "replacement card payment still fails and the authorization credential "
    "may need a refresh"
)
SCENARIO_APPLICABILITY: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "stale_payment_token": (
        frozenset({"card_replaced", "stale_token"}),
        frozenset({"insufficient_funds", "account_blocked"}),
    ),
    "billing_profile_mismatch": (
        frozenset({"billing_profile_mismatch"}),
        frozenset({"account_blocked"}),
    ),
    "transient_issuer_outage": (
        frozenset({"transient_issuer_outage"}),
        frozenset({"account_blocked"}),
    ),
}
SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "content-security-policy": (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'"
    ),
}
_READINESS_CACHE: tuple[float, tuple[int, dict[str, Any]]] | None = None
_SECURITY_RECONCILE_AT = 0.0
MAX_REQUEST_BODY_BYTES = 16 * 1024
MAX_SCOPE_ID_CHARS = 256
MAX_SITUATION_CHARS = 4096
INTERNAL_PRODUCER_AGENT_IDS = frozenset(
    {"recovery-observer", "recovery-observer-a", "recovery-observer-b"}
)


class SupersessionConflict(Exception):
    """The requested correction targets a non-current or concurrently replaced head."""


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class ExecutionPolicyConflict(Exception):
    """Execution is blocked because the current deterministic decision disagrees."""


def _embedding_revision() -> str:
    revision = os.getenv("NVIDIA_EMBED_REVISION", "").strip()
    if not revision:
        raise RuntimeError("NVIDIA_EMBED_REVISION is required for semantic memory")
    return revision


def _bounded_provider_timeout(*, maximum_seconds: float) -> float:
    configured = float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20"))
    if configured <= 0:
        raise RuntimeError("NVIDIA_TIMEOUT_SECONDS must be positive")
    return min(maximum_seconds, configured)


def _semantic_runtime_timeout() -> float:
    # Preserve room inside the 30s Lambda deadline for the bounded CockroachDB
    # statement timeout and response/serialization overhead.
    return _bounded_provider_timeout(maximum_seconds=12.0)


def _advisor_runtime_timeout() -> float:
    # The advisor is non-authoritative and runs after the deterministic
    # decision. Keep its deadline short enough for graceful fallback to return.
    return _bounded_provider_timeout(maximum_seconds=5.0)


def _current_semantic_embedding_space() -> str:
    return semantic_embedding_space(
        os.getenv("NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"),
        revision=_embedding_revision(),
    )


def _json_response(
    status_code: int,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response_headers = {"content-type": "application/json", **SECURITY_HEADERS}
    if headers:
        response_headers.update(headers)
    return {
        "statusCode": status_code,
        "headers": response_headers,
        "body": json.dumps(payload, separators=(",", ":")),
    }


def _html_response(html: str) -> dict[str, Any]:
    return {
        "statusCode": 200,
        "headers": {
            "content-type": "text/html; charset=utf-8",
            "cache-control": "no-store",
            **SECURITY_HEADERS,
        },
        "body": html,
    }


def _request_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if body in (None, ""):
        return {}
    if event.get("isBase64Encoded"):
        decoded = base64.b64decode(body)
        if len(decoded) > MAX_REQUEST_BODY_BYTES:
            raise ValueError("request body is too large")
        body = decoded.decode("utf-8")
    if isinstance(body, dict):
        if len(json.dumps(body, ensure_ascii=False).encode("utf-8")) > MAX_REQUEST_BODY_BYTES:
            raise ValueError("request body is too large")
        return body
    if len(str(body).encode("utf-8")) > MAX_REQUEST_BODY_BYTES:
        raise ValueError("request body is too large")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _bounded_text(
    value: Any,
    *,
    field: str,
    maximum_chars: int,
    required: bool = True,
) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{field} is required")
    if len(text) > maximum_chars:
        raise ValueError(f"{field} must be at most {maximum_chars} characters")
    return text


def _demo_authorized(event: dict[str, Any]) -> bool:
    expected = os.getenv("DEMO_API_TOKEN", "").strip()
    if not expected:
        return True
    headers = {
        str(key).lower(): str(value)
        for key, value in (event.get("headers") or {}).items()
    }
    return headers.get("x-decisionvault-token", "") == expected


def _agent_grants() -> dict[str, AgentGrant]:
    return load_agent_grants(os.getenv("AGENT_AUTH_JSON", ""))


def _agent_token(event: dict[str, Any]) -> str:
    headers = {
        str(key).lower(): str(value)
        for key, value in (event.get("headers") or {}).items()
    }
    return headers.get("x-decisionvault-agent-token", "")


def _authenticate_request_agent(
    event: dict[str, Any],
    *,
    permission: str,
    scope_id: str,
) -> AgentGrant | None:
    return authenticate_agent(
        token=_agent_token(event),
        grants=_agent_grants(),
        permission=permission,
        scope_id=scope_id,
    )


def _revoke_agent_ids() -> frozenset[str]:
    return frozenset(
        item.strip()
        for item in os.getenv("REVOKE_AGENT_IDS", "").split(",")
        if item.strip()
    )


def _authenticate_revoke_agent(
    event: dict[str, Any],
    *,
    scope_id: str,
) -> AgentGrant | None:
    grants = _agent_grants()
    token = _agent_token(event)
    grant = authenticate_agent(
        token=token,
        grants=grants,
        permission="revoke",
        scope_id=scope_id,
    )
    if grant is None:
        # Compatibility bridge for already-deployed grants: a record-capable
        # identity may revoke only when that server-bound agent_id is also
        # explicitly opted into the non-secret Lambda allowlist. New grant
        # generations may carry the distinct `revoke` permission directly, but
        # the allowlist remains a second server-side authorization boundary.
        grant = authenticate_agent(
            token=token,
            grants=grants,
            permission="record",
            scope_id=scope_id,
        )
    if grant is None or grant.agent_id not in _revoke_agent_ids():
        return None
    return grant


def _producer_trust_registry() -> dict[str, float]:
    registry = {
        grant.agent_id: grant.trust
        for grant in _agent_grants().values()
    }
    # These identities are server-owned by the atomic judge demos and cannot be
    # supplied through the public /record or /decide APIs.
    registry.update(
        {
            "recovery-observer": 1.0,
            "recovery-observer-a": 1.0,
            "recovery-observer-b": 1.0,
        }
    )
    return registry


def _refresh_runtime_security_state(*, force: bool = False) -> None:
    """Refresh managed secrets and retire heads from no-longer-authorized producers."""

    if force:
        hydrate_runtime_secrets(force=True)
    else:
        hydrate_runtime_secrets()
    if not os.getenv("DECISIONVAULT_SECRET_ARN", "").strip():
        return
    global _SECURITY_RECONCILE_AT
    now = time.monotonic()
    interval = max(1.0, float(os.getenv("SECURITY_RECONCILE_SECONDS", "30")))
    if not force and now - _SECURITY_RECONCILE_AT < interval:
        return
    grants = _agent_grants()
    active = {grant.agent_id for grant in grants.values()} | set(
        INTERNAL_PRODUCER_AGENT_IDS
    )
    retirement = _build_memory_store().retire_untrusted_heads(
        active_producer_agent_ids=active,
        reason="producer authorization retired by runtime grant reconciliation",
    )
    for scope_id in retirement.scope_ids:
        _best_effort_consolidation(scope_id)
    _SECURITY_RECONCILE_AT = now


def _execution_secret() -> str:
    secret = os.getenv("EXECUTION_RECEIPT_SECRET", "").strip()
    if len(secret) < 16:
        raise RuntimeError("EXECUTION_RECEIPT_SECRET is not configured")
    return secret


def _build_memory_store() -> CockroachVectorMemoryStore:
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    if nvidia_key:
        semantic = NvidiaSemanticEmbedder(
            api_key=nvidia_key,
            revision=_embedding_revision(),
            model_id=os.getenv(
                "NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"
            ),
            base_url=os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ),
            timeout_seconds=_semantic_runtime_timeout(),
        )
        store = CockroachVectorMemoryStore(
            connection_factory=psycopg_connection_factory(),
            embedder=deterministic_text_embedding,
            semantic_embedder=semantic.embed_passage,
            semantic_query_embedder=semantic.embed_query,
            semantic_embedding_space=semantic.embedding_space,
        )
    else:
        store = CockroachVectorMemoryStore(
            connection_factory=psycopg_connection_factory(),
            embedder=deterministic_text_embedding,
        )
    return store


def _build_consolidation_service() -> CockroachMemoryConsolidationService:
    store = _build_memory_store()
    if store.semantic_embedder is None or not (store.semantic_embedding_space or "").strip():
        raise RuntimeError("semantic embedding is required for adaptive consolidation")
    return CockroachMemoryConsolidationService(
        connection_factory=store.connection_factory,
        semantic_embedder=store.semantic_embedder,
        semantic_embedding_space=str(store.semantic_embedding_space),
    )


def _consolidate_scope(scope_id: str) -> dict[str, Any]:
    active_producers = set(_producer_trust_registry())
    result = _build_consolidation_service().consolidate_scope(
        scope_id=scope_id,
        scope_level=MemoryScopeLevel.TEAM,
        active_producer_agent_ids=active_producers,
    )
    return {
        "status": "COMPLETE",
        "candidate_count": result.candidate_count,
        "promoted_count": result.promoted_count,
        "abstained_count": result.abstained_count,
        "memory_ids": list(result.memory_ids),
        "resolutions": list(result.resolutions),
        "governance_revision": ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
    }


def _best_effort_consolidation(scope_id: str) -> dict[str, Any]:
    """Consolidate without making committed L1/revocation writes non-idempotent.

    Promotion is optional authority: failure means *less* reusable memory, never
    an ungoverned fallback. Readiness still fails closed when the adaptive
    schema/provider is unhealthy; this wrapper only preserves durable outcome
    and revocation semantics after those writes have already committed.
    """

    try:
        return _consolidate_scope(scope_id)
    except Exception as exc:
        return {
            "status": "DEFERRED",
            "candidate_count": 0,
            "promoted_count": 0,
            "abstained_count": 0,
            "memory_ids": [],
            "resolutions": [f"CONSOLIDATION_DEFERRED:{type(exc).__name__}"],
            "governance_revision": ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
        }


def _build_agent(
    *,
    memory_enabled: bool,
    agent_id: str = "recovery-planner",
) -> DecisionAgent:
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
    store = _build_memory_store()
    advisor = None
    if nvidia_key:
        advisor = NvidiaDecisionAdvisor(
            api_key=nvidia_key,
            model_id=os.getenv(
                "NVIDIA_MODEL_ID", "meta/llama-3.1-8b-instruct"
            ),
            base_url=os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ),
            timeout_seconds=_advisor_runtime_timeout(),
        )
    return DecisionAgent(
        memory=store,
        policy=OutcomeAwarePolicy(
            resolver=ConflictAwareMemoryResolver(
                minimum_similarity=PRODUCTION_SEMANTIC_MIN_SIMILARITY,
                producer_trust=_producer_trust_registry(),
            )
        ),
        memory_enabled=memory_enabled,
        advisor=advisor,
        agent_id=agent_id,
    )


def _delete_scope(scope_id: str) -> None:
    conn = psycopg_connection_factory()()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM decision_governed_memory_support
                WHERE memory_id IN (
                    SELECT memory_id FROM decision_governed_memories
                    WHERE scope_id = %s
                )
                """,
                (scope_id,),
            )
            cur.execute(
                "DELETE FROM decision_governed_memories WHERE scope_id = %s",
                (scope_id,),
            )
            cur.execute(
                "DELETE FROM decision_memory_consolidation_candidates WHERE scope_id = %s",
                (scope_id,),
            )
            cur.execute(
                "DELETE FROM decision_strategy_effectiveness WHERE scope_id = %s",
                (scope_id,),
            )
            cur.execute(
                "DELETE FROM decision_memory_heads WHERE scope_id = %s",
                (scope_id,),
            )
            cur.execute(
                "DELETE FROM decision_episodes WHERE scope_id = %s",
                (scope_id,),
            )
        conn.commit()
    finally:
        conn.close()


def _health() -> dict[str, Any]:
    managed_secret = bool(os.getenv("DECISIONVAULT_SECRET_ARN", "").strip())
    embedding_revision = os.getenv("NVIDIA_EMBED_REVISION", "").strip()
    configured_embedding_space = (
        semantic_embedding_space(
            os.getenv("NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"),
            revision=embedding_revision,
        )
        if embedding_revision
        else None
    )
    try:
        validate_nvidia_base_url(os.getenv("NVIDIA_BASE_URL"))
        nvidia_provider_origin_valid = True
    except ValueError:
        nvidia_provider_origin_valid = False
    return {
        "service": "decisionvault",
        "status": "ok",
        "memory_backend": "cockroachdb-cloud",
        "database_configured": managed_secret or bool(os.getenv("DATABASE_URL")),
        "nvidia_advisor_configured": managed_secret
        or bool(os.getenv("NVIDIA_API_KEY")),
        "semantic_embedding_configured": managed_secret
        or bool(os.getenv("NVIDIA_API_KEY")),
        "semantic_embedding_revision_configured": bool(embedding_revision),
        "semantic_embedding_space": configured_embedding_space,
        "nvidia_provider_origin_valid": nvidia_provider_origin_valid,
        "execution_receipt_signing_configured": managed_secret
        or bool(os.getenv("EXECUTION_RECEIPT_SECRET", "").strip()),
        "runtime_secret_source": (
            "aws-secrets-manager"
            if managed_secret
            else "environment"
        ),
        "runtime_secret_reference_configured": managed_secret,
    }


def _liveness() -> dict[str, Any]:
    return {"service": "decisionvault", "status": "live"}


def _probe_readiness() -> tuple[int, dict[str, Any]]:
    secret_ok = False
    database_ok = False
    semantic_embedding_ok = False
    semantic_embedding_revision_ok = False
    nvidia_provider_origin_ok = False
    semantic_head_space_ok = False
    governance_schema_ok = False
    adaptive_memory_schema_ok = False
    adaptive_memory_current_ok = False
    agent_auth_ok = False
    receipt_signing_ok = False
    demo_auth_ok = False
    sandbox_config_ok = False
    configured_embedding_space: str | None = None
    errors: list[str] = []

    try:
        hydrate_runtime_secrets()
        secret_ok = True
    except Exception as exc:
        errors.append(f"secrets:{type(exc).__name__}")

    if secret_ok:
        try:
            grants = _agent_grants()
            if not grants:
                raise ValueError("no agent grants configured")
            agent_auth_ok = True
        except Exception as exc:
            errors.append(f"agent_auth:{type(exc).__name__}")

        try:
            _execution_secret()
            receipt_signing_ok = True
        except Exception as exc:
            errors.append(f"execution_receipt:{type(exc).__name__}")

        demo_auth_ok = bool(os.getenv("DEMO_API_TOKEN", "").strip())
        if not demo_auth_ok:
            errors.append("demo_auth:MissingToken")

        try:
            configured_sandbox_scenario(
                os.getenv("EXECUTION_SANDBOX_SCENARIO", "stale_payment_token")
            )
            sandbox_config_ok = True
        except Exception as exc:
            errors.append(f"execution_sandbox:{type(exc).__name__}")

        try:
            conn = psycopg_connection_factory()()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    database_ok = cur.fetchone()[0] == 1
                    cur.execute(
                        "SELECT semantic_embedding_space, observed_at, recorded_at "
                        "FROM decision_memory_heads LIMIT 0"
                    )
                    cur.execute(
                        "SELECT observed_at, recorded_at "
                        "FROM decision_episodes LIMIT 0"
                    )
                    cur.execute(
                        "SELECT revocation_id FROM decision_memory_revocations LIMIT 0"
                    )
                    configured_embedding_space = _current_semantic_embedding_space()
                    cur.execute(
                        "SELECT count(*) FROM decision_memory_heads "
                        "WHERE semantic_embedding_space IS DISTINCT FROM %s",
                        (configured_embedding_space,),
                    )
                    semantic_head_space_ok = int(cur.fetchone()[0]) == 0
                    if not semantic_head_space_ok:
                        raise RuntimeError(
                            "current semantic heads require embedding-space migration"
                        )
                    cur.execute(
                        """
                        SELECT candidate_id, supporting_episode_ids,
                               rule_key, governance_revision, semantic_embedding_space,
                               status, observed_from, observed_to
                        FROM decision_memory_consolidation_candidates LIMIT 0
                        """
                    )
                    cur.execute(
                        """
                        SELECT memory_id, candidate_id, supporting_episode_ids,
                               producer_set, rule_key, governance_revision,
                               semantic_embedding_space, status,
                               supersedes_memory_id, observed_from, observed_to
                        FROM decision_governed_memories LIMIT 0
                        """
                    )
                    cur.execute(
                        """
                        SELECT memory_id, episode_id, producer_agent_id
                        FROM decision_governed_memory_support LIMIT 0
                        """
                    )
                    cur.execute(
                        """
                        SELECT scope_id, situation_class, strategy,
                               semantic_embedding_space, sample_count,
                               success_count, failure_count, effectiveness,
                               independent_producer_count, confidence,
                               observed_to, recorded_at, governance_revision
                        FROM decision_strategy_effectiveness LIMIT 0
                        """
                    )
                    adaptive_memory_schema_ok = True
                    cur.execute(
                        """
                        SELECT count(*)
                        FROM decision_governed_memories
                        WHERE status = 'ACTIVE'
                          AND (
                            semantic_embedding_space IS DISTINCT FROM %s
                            OR governance_revision IS DISTINCT FROM %s
                          )
                        """,
                        (
                            configured_embedding_space,
                            ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
                        ),
                    )
                    adaptive_memory_current_ok = int(cur.fetchone()[0]) == 0
                    if not adaptive_memory_current_ok:
                        raise RuntimeError(
                            "active adaptive memories require governance/embedding migration"
                        )
                    cur.execute(
                        """
                        SELECT count(*)
                        FROM decision_governed_memories m
                        WHERE m.status = 'ACTIVE'
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
                        """
                    )
                    if int(cur.fetchone()[0]) != 0:
                        adaptive_memory_current_ok = False
                        raise RuntimeError(
                            "active adaptive memory has non-current supporting evidence"
                        )
                    cur.execute(
                        """
                        SELECT count(*)
                        FROM decision_strategy_effectiveness
                        WHERE semantic_embedding_space IS DISTINCT FROM %s
                           OR governance_revision IS DISTINCT FROM %s
                        """,
                        (
                            configured_embedding_space,
                            ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
                        ),
                    )
                    if int(cur.fetchone()[0]) != 0:
                        adaptive_memory_current_ok = False
                        raise RuntimeError(
                            "strategy effectiveness projection requires migration"
                        )
                    governance_schema_ok = True
            finally:
                conn.close()
        except Exception as exc:
            errors.append(f"database:{type(exc).__name__}")

        try:
            _embedding_revision()
            semantic_embedding_revision_ok = True
        except Exception as exc:
            errors.append(f"semantic_embedding_revision:{type(exc).__name__}")

        try:
            validate_nvidia_base_url(os.getenv("NVIDIA_BASE_URL"))
            nvidia_provider_origin_ok = True
        except Exception as exc:
            errors.append(f"nvidia_provider_origin:{type(exc).__name__}")

        try:
            semantic = NvidiaSemanticEmbedder(
                api_key=os.getenv("NVIDIA_API_KEY", "").strip(),
                revision=_embedding_revision(),
                model_id=os.getenv(
                    "NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"
                ),
                base_url=os.getenv(
                    "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
                ),
                timeout_seconds=min(
                    8.0, float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20"))
                ),
            )
            semantic_embedding_ok = (
                len(semantic.embed_query("DecisionVault readiness probe")) == 1024
            )
            configured_embedding_space = semantic.embedding_space
        except Exception as exc:
            errors.append(f"semantic_embedding:{type(exc).__name__}")

    ready = all(
        (
            secret_ok,
            database_ok,
            governance_schema_ok,
            adaptive_memory_schema_ok,
            adaptive_memory_current_ok,
            semantic_embedding_ok,
            semantic_embedding_revision_ok,
            semantic_head_space_ok,
            nvidia_provider_origin_ok,
            agent_auth_ok,
            receipt_signing_ok,
            demo_auth_ok,
            sandbox_config_ok,
        )
    )
    return (
        200 if ready else 503,
        {
            "service": "decisionvault",
            "status": "ready" if ready else "not_ready",
            "secrets_manager": secret_ok,
            "database": database_ok,
            "memory_governance_schema": governance_schema_ok,
            "adaptive_memory_schema": adaptive_memory_schema_ok,
            "adaptive_memory_current": adaptive_memory_current_ok,
            "adaptive_memory_governance_revision": ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
            "semantic_embedding": semantic_embedding_ok,
            "semantic_embedding_revision": semantic_embedding_revision_ok,
            "semantic_embedding_space": configured_embedding_space,
            "semantic_head_space_current": semantic_head_space_ok,
            "nvidia_provider_origin": nvidia_provider_origin_ok,
            "agent_auth": agent_auth_ok,
            "execution_receipt_signing": receipt_signing_ok,
            "demo_auth": demo_auth_ok,
            "execution_sandbox": sandbox_config_ok,
            "advisor_required_for_readiness": False,
            "errors": errors,
        },
    )


def _readiness() -> tuple[int, dict[str, Any]]:
    global _READINESS_CACHE
    now = time.monotonic()
    ttl = max(1.0, float(os.getenv("READINESS_CACHE_SECONDS", "30")))
    if _READINESS_CACHE is not None and now - _READINESS_CACHE[0] < ttl:
        return _READINESS_CACHE[1]
    result = _probe_readiness()
    _READINESS_CACHE = (now, result)
    return result


def _decide(body: dict[str, Any], *, agent_id: str) -> dict[str, Any]:
    scope_id = _bounded_text(
        body.get("scope_id"), field="scope_id", maximum_chars=MAX_SCOPE_ID_CHARS
    )
    situation = _bounded_text(
        body.get("situation"),
        field="situation",
        maximum_chars=MAX_SITUATION_CHARS,
    )

    if "memory_enabled" in body:
        raise ValueError(
            "memory_enabled is server-controlled on the general agent API"
        )
    decision = _build_agent(memory_enabled=True, agent_id=agent_id).decide(
        scope_id=scope_id,
        situation=situation,
    )
    payload = _decision_payload(decision)
    if decision.executable and decision.strategy is not None:
        digest = decision_state_digest(
            decision,
            semantic_embedding_space=_current_semantic_embedding_space(),
        )
        payload["decision_snapshot"] = issue_decision_snapshot(
            scope_id=scope_id,
            agent_id=agent_id,
            situation=situation,
            strategy=decision.strategy,
            decision_digest=digest,
            decision_provenance=decision_provenance_payload(decision),
            signing_secret=_execution_secret(),
        )
    else:
        payload["decision_snapshot"] = None
    return payload


def _execute(body: dict[str, Any], *, agent_id: str) -> dict[str, Any]:
    scope_id = _bounded_text(
        body.get("scope_id"), field="scope_id", maximum_chars=MAX_SCOPE_ID_CHARS
    )
    situation = _bounded_text(
        body.get("situation"),
        field="situation",
        maximum_chars=MAX_SITUATION_CHARS,
    )
    if "scenario" in body:
        raise ValueError("scenario is server-controlled and must not be supplied")
    scenario = configured_sandbox_scenario(
        os.getenv("EXECUTION_SANDBOX_SCENARIO", "stale_payment_token")
    )
    strategy = Strategy(str(body.get("strategy", "")))
    snapshot = verify_decision_snapshot(
        body.get("decision_snapshot"),
        signing_secret=_execution_secret(),
        expected_scope_id=scope_id,
        expected_situation=situation,
        expected_strategy=strategy,
    )
    policy_agent = _build_agent(
        memory_enabled=True,
        agent_id=agent_id,
    )
    if hasattr(policy_agent, "advisor"):
        policy_agent.advisor = None
    current_decision = policy_agent.decide(scope_id=scope_id, situation=situation)
    if not current_decision.executable or current_decision.strategy is None:
        raise ExecutionPolicyConflict(
            "current deterministic decision abstains; execution is blocked"
        )
    if current_decision.strategy != strategy:
        raise ExecutionPolicyConflict(
            "requested strategy does not match the current deterministic decision"
        )
    current_digest = decision_state_digest(
        current_decision,
        semantic_embedding_space=_current_semantic_embedding_space(),
    )
    if not hmac.compare_digest(snapshot.decision_digest, current_digest):
        raise DecisionSnapshotStale(
            "decision snapshot is stale relative to current policy/memory state"
        )
    receipt = issue_sandbox_receipt(
        scope_id=scope_id,
        agent_id=agent_id,
        situation=situation,
        strategy=strategy,
        scenario=scenario,
        signing_secret=_execution_secret(),
        decision_snapshot_id=snapshot.snapshot_id,
        decision_digest=snapshot.decision_digest,
        decision_revision=snapshot.decision_revision,
        decision_agent_id=snapshot.agent_id,
        decision_provenance=snapshot.decision_provenance,
    )
    return {
        "execution_receipt": receipt,
        "policy_decision": _decision_payload(current_decision),
        "verified_outcome_source": "decisionvault-payment-recovery-sandbox",
    }


def _episode_by_receipt(receipt_id: str) -> dict[str, Any] | None:
    conn = psycopg_connection_factory()()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT episode_id::STRING, strategy, outcome, effectiveness,
                       evidence->>'producer_agent_id', observed_at, recorded_at,
                       evidence->>'decision_provenance'
                FROM decision_episodes
                WHERE execution_receipt_id = %s
                LIMIT 1
                """,
                (receipt_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    result = {
        "episode_id": row[0],
        "strategy": row[1],
        "outcome": row[2],
        "effectiveness": float(row[3]),
        "producer_agent_id": row[4],
        "observed_at": row[5].isoformat(),
        "recorded_at": row[6].isoformat(),
        "execution_receipt_id": receipt_id,
        "idempotent_replay": True,
    }
    if row[7]:
        try:
            provenance = json.loads(str(row[7]))
        except json.JSONDecodeError:
            provenance = None
        if isinstance(provenance, dict):
            result["decision_provenance"] = provenance
    return result


def _validate_supersession(
    *,
    scope_id: str,
    agent_id: str,
    supersedes_episode_id: str,
) -> str:
    try:
        target_id = str(UUID(supersedes_episode_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("supersedes_episode_id must be a valid UUID") from exc

    conn = psycopg_connection_factory()()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    e.evidence->>'producer_agent_id' AS producer_agent_id,
                    EXISTS (
                        SELECT 1
                        FROM decision_memory_heads h
                        WHERE h.scope_id = e.scope_id
                          AND h.episode_id = e.episode_id
                    ) AS is_current_head
                FROM decision_episodes e
                WHERE e.episode_id = %s::UUID AND e.scope_id = %s
                """,
                (target_id, scope_id),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        raise ValueError("supersession target does not exist in the requested scope")
    producer_agent_id = str(row[0] or "")
    if producer_agent_id != agent_id:
        raise ValueError("an agent may supersede only its own outcome memory")
    if not bool(row[1]):
        raise SupersessionConflict(
            "supersession target is not the current governed head"
        )
    return target_id


def _decision_payload(decision: Decision) -> dict[str, Any]:
    return {
        "strategy": decision.strategy.value if decision.strategy is not None else None,
        "action": decision.action.value,
        "executable": decision.executable,
        "reason": decision.reason,
        "memory_influenced": decision.memory_influenced,
        "recalled_episode_ids": list(decision.recalled_episode_ids),
        "recalled_memory_ids": list(decision.recalled_memory_ids),
        "recalled_producer_agent_ids": list(decision.recalled_producer_agent_ids),
        "memory_resolution": decision.memory_resolution,
        "memory_conflict": decision.memory_conflict,
        "governance_trace": asdict(decision.governance_trace),
        "model_provider": decision.model_provider,
        "model_explanation": decision.model_explanation,
    }


def _demo() -> dict[str, Any]:
    scope_id = f"phase7-demo-{uuid4()}"
    producer_agent_id = "recovery-observer"
    consumer_agent_id = "recovery-planner"
    result: dict[str, Any] = {}
    try:
        _build_agent(
            memory_enabled=True,
            agent_id=producer_agent_id,
        ).record_outcome(
            scope_id=scope_id,
            situation=DEMO_FIRST_CASE,
            decision=Decision(
                strategy=Strategy.GENERIC_RETRY,
                reason="demo seed: default retry before persistent outcome memory",
            ),
            outcome=Outcome.FAILED,
            effectiveness=0.1,
            confidence=1.0,
        )
        memory_off = _build_agent(
            memory_enabled=False,
            agent_id=consumer_agent_id,
        ).decide(
            scope_id=scope_id,
            situation=DEMO_SIMILAR_CASE,
        )
        memory_on = _build_agent(
            memory_enabled=True,
            agent_id=consumer_agent_id,
        ).decide(
            scope_id=scope_id,
            situation=DEMO_SIMILAR_CASE,
        )
        result = {
            "memory_off": _decision_payload(memory_off),
            "memory_on": _decision_payload(memory_on),
            "expected_change": (
                memory_off.strategy == Strategy.GENERIC_RETRY
                and memory_on.strategy == Strategy.REFRESH_PAYMENT_TOKEN
                and memory_on.memory_influenced
            ),
            "producer_agent_id": producer_agent_id,
            "consumer_agent_id": consumer_agent_id,
            "cross_agent_memory_used": (
                producer_agent_id in memory_on.recalled_producer_agent_ids
            ),
        }
    finally:
        _delete_scope(scope_id)
    result["cleaned"] = True
    return result


def _governance_demo() -> dict[str, Any]:
    scope_id = f"phase-governance-demo-{uuid4()}"
    producer_a = "recovery-observer-a"
    producer_b = "recovery-observer-b"
    consumer = "recovery-supervisor"
    result: dict[str, Any] = {}
    try:
        _build_agent(memory_enabled=True, agent_id=producer_a).record_outcome(
            scope_id=scope_id,
            situation=GOVERNANCE_CONFLICT_CASE,
            decision=Decision(
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                reason="producer A observed a successful token refresh",
            ),
            outcome=Outcome.SUCCESS,
            effectiveness=0.9,
            confidence=1.0,
        )
        _build_agent(memory_enabled=True, agent_id=producer_b).record_outcome(
            scope_id=scope_id,
            situation=GOVERNANCE_CONFLICT_CASE,
            decision=Decision(
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                reason="producer B observed the same strategy fail",
            ),
            outcome=Outcome.FAILED,
            effectiveness=0.1,
            confidence=1.0,
        )
        decision = _build_agent(memory_enabled=True, agent_id=consumer).decide(
            scope_id=scope_id,
            situation=GOVERNANCE_CONFLICT_CASE,
        )
        result = {
            "decision": _decision_payload(decision),
            "producer_agent_ids": [producer_a, producer_b],
            "consumer_agent_id": consumer,
            "expected_abstention": (
                decision.strategy is None
                and decision.action == DecisionAction.ABSTAIN
                and not decision.executable
                and not decision.memory_influenced
                and decision.memory_conflict
                and decision.memory_resolution == "CONFLICT_ABSTAIN"
            ),
        }
    finally:
        _delete_scope(scope_id)
    result["cleaned"] = True
    return result


def _record(body: dict[str, Any], *, agent_id: str) -> dict[str, Any]:
    scope_id = _bounded_text(
        body.get("scope_id"), field="scope_id", maximum_chars=MAX_SCOPE_ID_CHARS
    )
    forbidden = {
        key
        for key in ("agent_id", "situation", "strategy", "outcome", "effectiveness", "confidence")
        if key in body
    }
    if forbidden:
        raise ValueError(
            "direct outcome fields are not accepted; use execution_receipt"
        )
    receipt = verify_execution_receipt(
        body.get("execution_receipt"),
        signing_secret=_execution_secret(),
        expected_scope_id=scope_id,
        expected_agent_id=agent_id,
        ttl_seconds=None,
    )
    if len(receipt.situation) > MAX_SITUATION_CHARS:
        raise ValueError(
            f"execution receipt situation must be at most {MAX_SITUATION_CHARS} characters"
        )
    existing = _episode_by_receipt(receipt.receipt_id)
    if existing is not None:
        return existing
    receipt = verify_execution_receipt(
        body.get("execution_receipt"),
        signing_secret=_execution_secret(),
        expected_scope_id=scope_id,
        expected_agent_id=agent_id,
    )

    evidence: dict[str, str] = {
        "execution_receipt_id": receipt.receipt_id,
        "execution_scenario": receipt.scenario,
        "execution_issued_at": receipt.issued_at.isoformat(),
        "execution_verified": "true",
        "execution_outcome_source": "decisionvault-payment-recovery-sandbox",
        "situation_class": receipt.scenario,
    }
    required, excluded = SCENARIO_APPLICABILITY.get(
        receipt.scenario, (frozenset(), frozenset())
    )
    context_tags = set(derive_context_tags(receipt.situation))
    context_tags.update(required)
    evidence["preconditions"] = ",".join(sorted(context_tags))
    evidence["exclusions"] = ",".join(sorted(excluded))
    if receipt.decision_snapshot_id:
        evidence["decision_snapshot_id"] = receipt.decision_snapshot_id
    if receipt.decision_digest:
        evidence["decision_digest"] = receipt.decision_digest
    if receipt.decision_revision:
        evidence["decision_revision"] = receipt.decision_revision
    if receipt.decision_agent_id:
        evidence["decision_agent_id"] = receipt.decision_agent_id
    if receipt.decision_provenance:
        evidence["decision_provenance"] = json.dumps(
            dict(receipt.decision_provenance),
            sort_keys=True,
            separators=(",", ":"),
        )
        recalled_memory_ids = receipt.decision_provenance.get(
            "recalled_memory_ids", []
        )
        if isinstance(recalled_memory_ids, list):
            evidence["decision_recalled_memory_ids"] = ",".join(
                str(item) for item in recalled_memory_ids
            )
        evidence["decision_memory_resolution"] = str(
            receipt.decision_provenance.get("memory_resolution", "")
        )
    supersedes_episode_id = str(body.get("supersedes_episode_id", "")).strip()
    if supersedes_episode_id:
        evidence["supersedes_episode_id"] = _validate_supersession(
            scope_id=scope_id,
            agent_id=agent_id,
            supersedes_episode_id=supersedes_episode_id,
        )
    decision = Decision(
        strategy=receipt.strategy,
        reason=f"verified execution receipt {receipt.receipt_id}",
    )
    try:
        episode = _build_agent(memory_enabled=True, agent_id=agent_id).record_outcome(
            scope_id=scope_id,
            situation=receipt.situation,
            decision=decision,
            outcome=receipt.outcome,
            effectiveness=receipt.effectiveness,
            confidence=receipt.confidence,
            evidence=evidence,
            observed_at=receipt.issued_at,
        )
    except Exception as exc:
        # The unique execution_receipt_id index is the final race-safe idempotency
        # boundary. If a concurrent writer won, return the already-recorded row.
        existing = _episode_by_receipt(receipt.receipt_id)
        if existing is not None:
            return existing
        if supersedes_episode_id and type(exc).__name__ == "UniqueViolation":
            raise SupersessionConflict(
                "supersession target already has a competing successor"
            ) from exc
        raise
    result = {
        "episode_id": episode.episode_id,
        "strategy": episode.strategy.value,
        "outcome": episode.outcome.value,
        "effectiveness": episode.effectiveness,
        "producer_agent_id": episode.evidence.get("producer_agent_id"),
        "observed_at": episode.observed_at.isoformat(),
        "recorded_at": episode.recorded_at.isoformat(),
        "execution_receipt_id": receipt.receipt_id,
        "idempotent_replay": False,
    }
    result["consolidation"] = _best_effort_consolidation(scope_id)
    return result


def _revoke(body: dict[str, Any], *, agent_id: str) -> dict[str, Any]:
    scope_id = _bounded_text(
        body.get("scope_id"), field="scope_id", maximum_chars=MAX_SCOPE_ID_CHARS
    )
    episode_id = str(body.get("episode_id", "")).strip()
    reason = str(body.get("reason", "")).strip()
    if not episode_id or not reason:
        raise ValueError("episode_id and reason are required")
    if len(reason) > 500:
        raise ValueError("revocation reason must be at most 500 characters")
    try:
        episode_id = str(UUID(episode_id))
    except (ValueError, AttributeError) as exc:
        raise ValueError("episode_id must be a valid UUID") from exc

    result = _build_memory_store().revoke_current_head(
        scope_id=scope_id,
        producer_agent_id=agent_id,
        episode_id=episode_id,
        reason=reason,
    )
    payload = {
        "revocation_id": result.revocation_id,
        "episode_id": result.episode_id,
        "producer_agent_id": result.producer_agent_id,
        "revoked": True,
        "idempotent_replay": result.idempotent_replay,
    }
    if not result.idempotent_replay:
        payload["consolidation"] = _best_effort_consolidation(scope_id)
    return payload


def _enforce_rate_limit(
    *,
    principal_id: str,
    route_group: str,
    limit: int,
) -> None:
    decision = CockroachRateLimiter(psycopg_connection_factory()).check(
        principal_id=principal_id,
        route_group=route_group,
        limit=limit,
    )
    if not decision.allowed:
        raise RateLimitExceeded(decision.retry_after_seconds)


def _handle_request(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    try:
        method = (
            event.get("requestContext", {})
            .get("http", {})
            .get("method", "POST")
            .upper()
        )
        path = str(event.get("rawPath", "/")).rstrip("/") or "/"
        if method == "GET" and path == "/":
            return _html_response(INDEX_HTML)
        if method == "GET" and path == "/health":
            return _json_response(200, _health())
        if method == "GET" and path == "/health/live":
            return _json_response(200, _liveness())
        if method == "GET" and path == "/health/ready":
            status_code, payload = _readiness()
            return _json_response(status_code, payload)

        body = _request_body(event)
        if method == "POST":
            _refresh_runtime_security_state()
        if method == "POST" and path == "/decide":
            scope_id = _bounded_text(
                body.get("scope_id"), field="scope_id", maximum_chars=MAX_SCOPE_ID_CHARS
            )
            grant = _authenticate_request_agent(
                event, permission="decide", scope_id=scope_id
            )
            if grant is None:
                return _json_response(403, {"error": "forbidden"})
            if "agent_id" in body:
                return _json_response(400, {"error": "agent_id_is_server_bound"})
            _enforce_rate_limit(
                principal_id=grant.agent_id,
                route_group="agent-api",
                limit=int(os.getenv("AGENT_RATE_LIMIT_PER_MINUTE", "60")),
            )
            return _json_response(200, _decide(body, agent_id=grant.agent_id))
        if method == "POST" and path == "/execute":
            scope_id = _bounded_text(
                body.get("scope_id"), field="scope_id", maximum_chars=MAX_SCOPE_ID_CHARS
            )
            grant = _authenticate_request_agent(
                event, permission="execute", scope_id=scope_id
            )
            if grant is None:
                return _json_response(403, {"error": "forbidden"})
            if "agent_id" in body:
                return _json_response(400, {"error": "agent_id_is_server_bound"})
            _enforce_rate_limit(
                principal_id=grant.agent_id,
                route_group="agent-api",
                limit=int(os.getenv("AGENT_RATE_LIMIT_PER_MINUTE", "60")),
            )
            return _json_response(200, _execute(body, agent_id=grant.agent_id))
        if method == "POST" and path == "/record":
            scope_id = _bounded_text(
                body.get("scope_id"), field="scope_id", maximum_chars=MAX_SCOPE_ID_CHARS
            )
            grant = _authenticate_request_agent(
                event, permission="record", scope_id=scope_id
            )
            if grant is None:
                return _json_response(403, {"error": "forbidden"})
            if "agent_id" in body:
                return _json_response(400, {"error": "agent_id_is_server_bound"})
            _enforce_rate_limit(
                principal_id=grant.agent_id,
                route_group="agent-api",
                limit=int(os.getenv("AGENT_RATE_LIMIT_PER_MINUTE", "60")),
            )
            return _json_response(201, _record(body, agent_id=grant.agent_id))
        if method == "POST" and path == "/revoke":
            scope_id = _bounded_text(
                body.get("scope_id"), field="scope_id", maximum_chars=MAX_SCOPE_ID_CHARS
            )
            grant = _authenticate_revoke_agent(event, scope_id=scope_id)
            if grant is None:
                return _json_response(403, {"error": "forbidden"})
            if "agent_id" in body:
                return _json_response(400, {"error": "agent_id_is_server_bound"})
            _enforce_rate_limit(
                principal_id=grant.agent_id,
                route_group="agent-api",
                limit=int(os.getenv("AGENT_RATE_LIMIT_PER_MINUTE", "60")),
            )
            return _json_response(200, _revoke(body, agent_id=grant.agent_id))
        if method == "POST" and path == "/demo":
            if not _demo_authorized(event):
                return _json_response(401, {"error": "unauthorized"})
            _enforce_rate_limit(
                principal_id="judge-demo",
                route_group="judge-demo",
                limit=int(os.getenv("DEMO_RATE_LIMIT_PER_MINUTE", "10")),
            )
            return _json_response(200, _demo())
        if method == "POST" and path == "/governance-demo":
            if not _demo_authorized(event):
                return _json_response(401, {"error": "unauthorized"})
            _enforce_rate_limit(
                principal_id="judge-demo",
                route_group="judge-demo",
                limit=int(os.getenv("DEMO_RATE_LIMIT_PER_MINUTE", "10")),
            )
            return _json_response(200, _governance_demo())
        return _json_response(404, {"error": "not_found"})
    except RateLimitExceeded as exc:
        return _json_response(
            429,
            {
                "error": "rate_limited",
                "retry_after_seconds": exc.retry_after_seconds,
            },
            headers={"retry-after": str(exc.retry_after_seconds)},
        )
    except (
        SupersessionConflict,
        SupersessionWriteConflict,
        MemoryRevocationConflict,
        ExecutionPolicyConflict,
        DecisionSnapshotStale,
    ) as exc:
        return _json_response(409, {"error": "conflict", "detail": str(exc)})
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return _json_response(400, {"error": "bad_request", "detail": str(exc)})
    except Exception as exc:
        return _json_response(
            500,
            {"error": "internal_error", "detail": type(exc).__name__},
        )


def _response_metric_flags(
    route: str,
    response: dict[str, Any],
) -> tuple[bool, bool, bool]:
    try:
        payload = json.loads(response.get("body") or "{}")
    except (TypeError, json.JSONDecodeError):
        return False, False, False
    if not isinstance(payload, dict):
        return False, False, False

    if route == "/demo":
        decision = payload.get("memory_on") or {}
        return (
            bool(decision.get("memory_influenced")),
            bool(decision.get("memory_conflict")),
            False,
        )
    if route == "/governance-demo":
        decision = payload.get("decision") or {}
        return (
            bool(decision.get("memory_influenced")),
            bool(decision.get("memory_conflict")),
            False,
        )
    return (
        bool(payload.get("memory_influenced")),
        bool(payload.get("memory_conflict")),
        bool(payload.get("idempotent_replay")),
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    started = time.monotonic()
    response = _handle_request(event, context)
    try:
        route = str(event.get("rawPath", "/")).rstrip("/") or "/"
        influenced, conflict, replay = _response_metric_flags(route, response)
        emit_request_metric(
            route=route,
            status_code=int(response.get("statusCode", 500)),
            latency_ms=(time.monotonic() - started) * 1000.0,
            memory_influenced=influenced,
            memory_conflict=conflict,
            idempotent_replay=replay,
        )
    except Exception:
        # Observability is non-authoritative and cannot change the API result.
        pass
    return response
