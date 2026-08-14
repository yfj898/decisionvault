from __future__ import annotations

import base64
import json
import os
import time
from typing import Any
from uuid import UUID, uuid4

from decisionvault.agent.engine import DecisionAgent
from decisionvault.agent.auth import AgentGrant, authenticate_agent, load_agent_grants
from decisionvault.agent.memory_governance import (
    PRODUCTION_SEMANTIC_MIN_SIMILARITY,
    ConflictAwareMemoryResolver,
)
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Decision, DecisionAction, Outcome, Strategy
from decisionvault.execution import (
    issue_sandbox_receipt,
    verify_execution_receipt,
)
from decisionvault.memory.cockroach import (
    CockroachVectorMemoryStore,
    MemoryRevocationConflict,
    SupersessionWriteConflict,
)
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import (
    NvidiaSemanticEmbedder,
    deterministic_text_embedding,
    semantic_embedding_space,
)
from decisionvault.observability import emit_request_metric
from decisionvault.providers.nvidia import NvidiaDecisionAdvisor
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


class SupersessionConflict(Exception):
    """The requested correction targets a non-current or concurrently replaced head."""


class RateLimitExceeded(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after_seconds = retry_after_seconds


class ExecutionPolicyConflict(Exception):
    """Execution is blocked because the current deterministic decision disagrees."""


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
        body = base64.b64decode(body).decode("utf-8")
    if isinstance(body, dict):
        return body
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


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
            model_id=os.getenv(
                "NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"
            ),
            base_url=os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ),
            timeout_seconds=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20")),
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
            timeout_seconds=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20")),
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
    configured_embedding_space = semantic_embedding_space(
        os.getenv("NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5")
    )
    return {
        "service": "decisionvault",
        "status": "ok",
        "memory_backend": "cockroachdb-cloud",
        "database_configured": managed_secret or bool(os.getenv("DATABASE_URL")),
        "nvidia_advisor_configured": managed_secret
        or bool(os.getenv("NVIDIA_API_KEY")),
        "semantic_embedding_configured": managed_secret
        or bool(os.getenv("NVIDIA_API_KEY")),
        "semantic_embedding_space": configured_embedding_space,
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
    governance_schema_ok = False
    configured_embedding_space: str | None = None
    errors: list[str] = []

    try:
        hydrate_runtime_secrets()
        secret_ok = True
    except Exception as exc:
        errors.append(f"secrets:{type(exc).__name__}")

    if secret_ok:
        try:
            conn = psycopg_connection_factory()()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    database_ok = cur.fetchone()[0] == 1
                    cur.execute(
                        "SELECT semantic_embedding_space "
                        "FROM decision_memory_heads LIMIT 0"
                    )
                    cur.execute(
                        "SELECT revocation_id FROM decision_memory_revocations LIMIT 0"
                    )
                    governance_schema_ok = True
            finally:
                conn.close()
        except Exception as exc:
            errors.append(f"database:{type(exc).__name__}")

        try:
            semantic = NvidiaSemanticEmbedder(
                api_key=os.getenv("NVIDIA_API_KEY", "").strip(),
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

    ready = secret_ok and database_ok and governance_schema_ok and semantic_embedding_ok
    return (
        200 if ready else 503,
        {
            "service": "decisionvault",
            "status": "ready" if ready else "not_ready",
            "secrets_manager": secret_ok,
            "database": database_ok,
            "memory_governance_schema": governance_schema_ok,
            "semantic_embedding": semantic_embedding_ok,
            "semantic_embedding_space": configured_embedding_space,
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
    scope_id = str(body.get("scope_id", "")).strip()
    situation = str(body.get("situation", "")).strip()
    if not scope_id or not situation:
        raise ValueError("scope_id and situation are required")

    memory_enabled = bool(body.get("memory_enabled", True))
    decision = _build_agent(memory_enabled=memory_enabled, agent_id=agent_id).decide(
        scope_id=scope_id,
        situation=situation,
    )
    return _decision_payload(decision)


def _execute(body: dict[str, Any], *, agent_id: str) -> dict[str, Any]:
    scope_id = str(body.get("scope_id", "")).strip()
    situation = str(body.get("situation", "")).strip()
    scenario = str(body.get("scenario", "")).strip()
    if not scope_id or not situation or not scenario:
        raise ValueError("scope_id, situation, and scenario are required")
    strategy = Strategy(str(body.get("strategy", "")))
    current_decision = _build_agent(
        memory_enabled=True,
        agent_id=agent_id,
    ).decide(scope_id=scope_id, situation=situation)
    if not current_decision.executable or current_decision.strategy is None:
        raise ExecutionPolicyConflict(
            "current deterministic decision abstains; execution is blocked"
        )
    if current_decision.strategy != strategy:
        raise ExecutionPolicyConflict(
            "requested strategy does not match the current deterministic decision"
        )
    receipt = issue_sandbox_receipt(
        scope_id=scope_id,
        agent_id=agent_id,
        situation=situation,
        strategy=strategy,
        scenario=scenario,
        signing_secret=_execution_secret(),
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
                       evidence->>'producer_agent_id'
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
    return {
        "episode_id": row[0],
        "strategy": row[1],
        "outcome": row[2],
        "effectiveness": float(row[3]),
        "producer_agent_id": row[4],
        "execution_receipt_id": receipt_id,
        "idempotent_replay": True,
    }


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
        "recalled_producer_agent_ids": list(decision.recalled_producer_agent_ids),
        "memory_resolution": decision.memory_resolution,
        "memory_conflict": decision.memory_conflict,
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
    scope_id = str(body.get("scope_id", "")).strip()
    if not scope_id:
        raise ValueError("scope_id is required")
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
    )
    existing = _episode_by_receipt(receipt.receipt_id)
    if existing is not None:
        return existing

    evidence: dict[str, str] = {
        "execution_receipt_id": receipt.receipt_id,
        "execution_scenario": receipt.scenario,
        "execution_verified": "true",
        "execution_outcome_source": "decisionvault-payment-recovery-sandbox",
    }
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
    return {
        "episode_id": episode.episode_id,
        "strategy": episode.strategy.value,
        "outcome": episode.outcome.value,
        "effectiveness": episode.effectiveness,
        "producer_agent_id": episode.evidence.get("producer_agent_id"),
        "execution_receipt_id": receipt.receipt_id,
        "idempotent_replay": False,
    }


def _revoke(body: dict[str, Any], *, agent_id: str) -> dict[str, Any]:
    scope_id = str(body.get("scope_id", "")).strip()
    episode_id = str(body.get("episode_id", "")).strip()
    reason = str(body.get("reason", "")).strip()
    if not scope_id or not episode_id or not reason:
        raise ValueError("scope_id, episode_id, and reason are required")
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
    return {
        "revocation_id": result.revocation_id,
        "episode_id": result.episode_id,
        "producer_agent_id": result.producer_agent_id,
        "revoked": True,
        "idempotent_replay": result.idempotent_replay,
    }


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

        if method == "POST":
            hydrate_runtime_secrets()
        body = _request_body(event)
        if method == "POST" and path == "/decide":
            scope_id = str(body.get("scope_id", "")).strip()
            if not scope_id:
                return _json_response(
                    400, {"error": "bad_request", "detail": "scope_id is required"}
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
            scope_id = str(body.get("scope_id", "")).strip()
            if not scope_id:
                return _json_response(
                    400, {"error": "bad_request", "detail": "scope_id is required"}
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
            scope_id = str(body.get("scope_id", "")).strip()
            if not scope_id:
                return _json_response(
                    400, {"error": "bad_request", "detail": "scope_id is required"}
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
            scope_id = str(body.get("scope_id", "")).strip()
            if not scope_id:
                return _json_response(
                    400, {"error": "bad_request", "detail": "scope_id is required"}
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
