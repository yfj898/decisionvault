from __future__ import annotations

import base64
import json
import os
from typing import Any
from uuid import uuid4

from decisionvault.agent.engine import DecisionAgent
from decisionvault.agent.memory_governance import ConflictAwareMemoryResolver
from decisionvault.agent.policy import OutcomeAwarePolicy
from decisionvault.domain import Decision, Outcome, Strategy
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import (
    NvidiaSemanticEmbedder,
    deterministic_text_embedding,
)
from decisionvault.providers.nvidia import NvidiaDecisionAdvisor
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


def _json_response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json", **SECURITY_HEADERS},
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


def _authorized(event: dict[str, Any]) -> bool:
    expected = os.getenv("DEMO_API_TOKEN", "").strip()
    if not expected:
        return True
    headers = {
        str(key).lower(): str(value)
        for key, value in (event.get("headers") or {}).items()
    }
    return headers.get("x-decisionvault-token", "") == expected


def _producer_trust_registry() -> dict[str, float]:
    raw = os.getenv("AGENT_TRUST_JSON", "").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("AGENT_TRUST_JSON must be a JSON object")
    registry: dict[str, float] = {}
    for agent_id, value in parsed.items():
        trust = float(value)
        if not 0.0 <= trust <= 1.0:
            raise ValueError("agent trust values must be between 0 and 1")
        registry[str(agent_id)] = trust
    return registry


def _build_agent(
    *,
    memory_enabled: bool,
    agent_id: str = "recovery-planner",
) -> DecisionAgent:
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
            embedder=semantic.embed_passage,
            query_embedder=semantic.embed_query,
        )
    else:
        store = CockroachVectorMemoryStore(
            connection_factory=psycopg_connection_factory(),
            embedder=deterministic_text_embedding,
        )
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
                producer_trust=_producer_trust_registry()
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
                "DELETE FROM decision_episodes WHERE scope_id = %s",
                (scope_id,),
            )
        conn.commit()
    finally:
        conn.close()


def _health() -> dict[str, Any]:
    return {
        "service": "decisionvault",
        "status": "ok",
        "memory_backend": "cockroachdb-cloud",
        "nvidia_advisor_configured": bool(os.getenv("NVIDIA_API_KEY")),
        "semantic_embedding_configured": bool(os.getenv("NVIDIA_API_KEY")),
        "database_configured": bool(os.getenv("DATABASE_URL")),
    }


def _decide(body: dict[str, Any]) -> dict[str, Any]:
    scope_id = str(body.get("scope_id", "")).strip()
    situation = str(body.get("situation", "")).strip()
    if not scope_id or not situation:
        raise ValueError("scope_id and situation are required")

    memory_enabled = bool(body.get("memory_enabled", True))
    agent_id = str(body.get("agent_id", "recovery-planner")).strip()
    decision = _build_agent(memory_enabled=memory_enabled, agent_id=agent_id).decide(
        scope_id=scope_id,
        situation=situation,
    )
    return _decision_payload(decision)


def _decision_payload(decision: Decision) -> dict[str, Any]:
    return {
        "strategy": decision.strategy.value,
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
                decision.strategy == Strategy.GENERIC_RETRY
                and not decision.memory_influenced
                and decision.memory_conflict
                and decision.memory_resolution == "CONFLICT_ABSTAIN"
            ),
        }
    finally:
        _delete_scope(scope_id)
    result["cleaned"] = True
    return result


def _record(body: dict[str, Any]) -> dict[str, Any]:
    scope_id = str(body.get("scope_id", "")).strip()
    situation = str(body.get("situation", "")).strip()
    if not scope_id or not situation:
        raise ValueError("scope_id and situation are required")

    strategy = Strategy(str(body.get("strategy", "")))
    outcome = Outcome(str(body.get("outcome", "")))
    effectiveness = float(body.get("effectiveness"))
    confidence = float(body.get("confidence", 1.0))
    agent_id = str(body.get("agent_id", "recovery-observer")).strip()
    evidence: dict[str, str] = {}
    supersedes_episode_id = str(body.get("supersedes_episode_id", "")).strip()
    if supersedes_episode_id:
        evidence["supersedes_episode_id"] = supersedes_episode_id
    decision = Decision(
        strategy=strategy,
        reason=str(body.get("decision_reason", "recorded via Lambda API")),
    )
    episode = _build_agent(memory_enabled=True, agent_id=agent_id).record_outcome(
        scope_id=scope_id,
        situation=situation,
        decision=decision,
        outcome=outcome,
        effectiveness=effectiveness,
        confidence=confidence,
        evidence=evidence,
    )
    return {
        "episode_id": episode.episode_id,
        "strategy": episode.strategy.value,
        "outcome": episode.outcome.value,
        "effectiveness": episode.effectiveness,
        "producer_agent_id": episode.evidence.get("producer_agent_id"),
    }


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
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

        if method == "POST" and not _authorized(event):
            return _json_response(401, {"error": "unauthorized"})

        body = _request_body(event)
        if method == "POST" and path == "/decide":
            return _json_response(200, _decide(body))
        if method == "POST" and path == "/record":
            return _json_response(201, _record(body))
        if method == "POST" and path == "/demo":
            return _json_response(200, _demo())
        if method == "POST" and path == "/governance-demo":
            return _json_response(200, _governance_demo())
        return _json_response(404, {"error": "not_found"})
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return _json_response(400, {"error": "bad_request", "detail": str(exc)})
    except Exception as exc:
        return _json_response(
            500,
            {"error": "internal_error", "detail": type(exc).__name__},
        )
