from __future__ import annotations

import base64
import json
import os
from typing import Any

from decisionvault.agent.engine import DecisionAgent
from decisionvault.domain import Decision, Outcome, Strategy
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import deterministic_text_embedding
from decisionvault.providers.nvidia import NvidiaDecisionAdvisor


def _json_response(status_code: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(payload, separators=(",", ":")),
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


def _build_agent(*, memory_enabled: bool) -> DecisionAgent:
    store = CockroachVectorMemoryStore(
        connection_factory=psycopg_connection_factory(),
        embedder=deterministic_text_embedding,
    )
    nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
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
        memory_enabled=memory_enabled,
        advisor=advisor,
    )


def _health() -> dict[str, Any]:
    return {
        "service": "decisionvault",
        "status": "ok",
        "memory_backend": "cockroachdb-cloud",
        "nvidia_advisor_configured": bool(os.getenv("NVIDIA_API_KEY")),
        "database_configured": bool(os.getenv("DATABASE_URL")),
    }


def _decide(body: dict[str, Any]) -> dict[str, Any]:
    scope_id = str(body.get("scope_id", "")).strip()
    situation = str(body.get("situation", "")).strip()
    if not scope_id or not situation:
        raise ValueError("scope_id and situation are required")

    memory_enabled = bool(body.get("memory_enabled", True))
    decision = _build_agent(memory_enabled=memory_enabled).decide(
        scope_id=scope_id,
        situation=situation,
    )
    return {
        "strategy": decision.strategy.value,
        "reason": decision.reason,
        "memory_influenced": decision.memory_influenced,
        "recalled_episode_ids": list(decision.recalled_episode_ids),
        "model_provider": decision.model_provider,
        "model_explanation": decision.model_explanation,
    }


def _record(body: dict[str, Any]) -> dict[str, Any]:
    scope_id = str(body.get("scope_id", "")).strip()
    situation = str(body.get("situation", "")).strip()
    if not scope_id or not situation:
        raise ValueError("scope_id and situation are required")

    strategy = Strategy(str(body.get("strategy", "")))
    outcome = Outcome(str(body.get("outcome", "")))
    effectiveness = float(body.get("effectiveness"))
    confidence = float(body.get("confidence", 1.0))
    decision = Decision(
        strategy=strategy,
        reason=str(body.get("decision_reason", "recorded via Lambda API")),
    )
    episode = _build_agent(memory_enabled=True).record_outcome(
        scope_id=scope_id,
        situation=situation,
        decision=decision,
        outcome=outcome,
        effectiveness=effectiveness,
        confidence=confidence,
    )
    return {
        "episode_id": episode.episode_id,
        "strategy": episode.strategy.value,
        "outcome": episode.outcome.value,
        "effectiveness": episode.effectiveness,
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
        if method == "GET" and path in {"/", "/health"}:
            return _json_response(200, _health())

        if method == "POST" and not _authorized(event):
            return _json_response(401, {"error": "unauthorized"})

        body = _request_body(event)
        if method == "POST" and path == "/decide":
            return _json_response(200, _decide(body))
        if method == "POST" and path == "/record":
            return _json_response(201, _record(body))
        return _json_response(404, {"error": "not_found"})
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return _json_response(400, {"error": "bad_request", "detail": str(exc)})
    except Exception as exc:
        return _json_response(
            500,
            {"error": "internal_error", "detail": type(exc).__name__},
        )
