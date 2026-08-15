from __future__ import annotations

import base64
from dataclasses import asdict
from datetime import datetime, timezone
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
from decisionvault.agent.auth import (
    AgentGrant,
    authenticate_agent,
    load_agent_grants,
    scope_prefix_matches,
)
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
from decisionvault.memory.outbox import ConsolidationOutbox, ConsolidationWorkItem
from decisionvault.memory_telemetry import (
    DEFAULT_CALIBRATION_INTERVAL_HOURS,
    DEFAULT_CALIBRATION_LOOKBACK_DAYS,
    DEFAULT_CALIBRATION_MAXIMUM_HARMFUL_RATE,
    DEFAULT_CALIBRATION_MINIMUM_SAMPLES,
    DEFAULT_CALIBRATION_MINIMUM_SUCCESS_RETENTION,
    DEFAULT_MEMORY_QUALITY_CALIBRATION_RUN_RETENTION_DAYS,
    DEFAULT_MEMORY_QUALITY_RAW_RETENTION_DAYS,
    calibration_is_due,
    insert_decision_quality_event,
    insert_outcome_quality_event,
    purge_memory_quality_retention,
    run_persisted_calibration,
)
from decisionvault.memory.embedding import (
    NvidiaSemanticEmbedder,
    deterministic_text_embedding,
    semantic_embedding_space,
)
from decisionvault.observability import emit_memory_metric, emit_request_metric
from decisionvault.providers.nvidia import NvidiaDecisionAdvisor
from decisionvault.providers.http_security import validate_nvidia_base_url
from decisionvault.rate_limit import CockroachRateLimiter
from decisionvault.runtime_secrets import hydrate_runtime_secrets
from decisionvault.semantic_benchmark import PRODUCTION_BENCHMARK_PRODUCER_AGENT_IDS
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
    {
        "recovery-observer",
        "recovery-observer-a",
        "recovery-observer-b",
        *PRODUCTION_BENCHMARK_PRODUCER_AGENT_IDS,
    }
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
    registry.update({agent_id: 1.0 for agent_id in INTERNAL_PRODUCER_AGENT_IDS})
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
    retired_heads = int(getattr(retirement, "retired_heads", 0))
    if retired_heads:
        try:
            emit_memory_metric(
                event_name="producer_retirement",
                producer_retired=retired_heads,
            )
        except Exception:
            pass
    for scope_id in retirement.scope_ids:
        _best_effort_consolidation(scope_id)
    _SECURITY_RECONCILE_AT = now


def _execution_secret() -> str:
    _, secret, _ = _execution_signing_material()
    return secret


def _execution_signing_material() -> tuple[str | None, str, dict[str, str]]:
    """Return active HMAC key plus retained verification-only keys."""

    secret = os.getenv("EXECUTION_RECEIPT_SECRET", "").strip()
    if len(secret) < 16:
        raise RuntimeError("EXECUTION_RECEIPT_SECRET is not configured")
    raw = os.getenv("EXECUTION_RECEIPT_KEYRING_JSON", "").strip()
    if not raw:
        return None, secret, {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("EXECUTION_RECEIPT_KEYRING_JSON is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("EXECUTION_RECEIPT_KEYRING_JSON must be an object")
    active_key_id = str(payload.get("active_key_id", "")).strip()
    raw_keys = payload.get("keys")
    if not active_key_id or not isinstance(raw_keys, dict):
        raise RuntimeError("execution signing keyring is missing active_key_id/keys")
    keys = {str(key): str(value) for key, value in raw_keys.items()}
    active_secret = keys.get(active_key_id, "")
    if len(active_secret) < 16:
        raise RuntimeError("execution signing keyring active key is missing or too short")
    if any(len(value) < 16 for value in keys.values()):
        raise RuntimeError("execution signing keyring contains a short verification key")
    return active_key_id, active_secret, keys


def _memory_scope_rules() -> tuple[
    MemoryScopeLevel, tuple[tuple[str, MemoryScopeLevel], ...]
]:
    default_raw = os.getenv("DEFAULT_MEMORY_SCOPE_LEVEL", "TEAM").strip().upper()
    try:
        default = MemoryScopeLevel(default_raw)
    except ValueError as exc:
        raise RuntimeError("DEFAULT_MEMORY_SCOPE_LEVEL is invalid") from exc

    raw = os.getenv("MEMORY_SCOPE_LEVELS_JSON", "").strip()
    if not raw:
        return default, ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("MEMORY_SCOPE_LEVELS_JSON is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("MEMORY_SCOPE_LEVELS_JSON must be an object")

    rules: list[tuple[str, MemoryScopeLevel]] = []
    for raw_prefix, raw_level in payload.items():
        prefix = str(raw_prefix).strip()
        if not prefix or "*" in prefix:
            raise RuntimeError("memory scope prefixes must be non-empty and wildcard-free")
        try:
            level = MemoryScopeLevel(str(raw_level).strip().upper())
        except ValueError as exc:
            raise RuntimeError("MEMORY_SCOPE_LEVELS_JSON contains an invalid level") from exc
        rules.append((prefix, level))
    rules.sort(key=lambda item: len(item[0]), reverse=True)
    return default, tuple(rules)


def _memory_scope_level(scope_id: str) -> MemoryScopeLevel:
    """Resolve a server-owned PRIVATE/TEAM/GLOBAL policy for one scope."""

    default, rules = _memory_scope_rules()
    matches = [
        (prefix, level)
        for prefix, level in rules
        if scope_prefix_matches(prefix, scope_id)
    ]
    if not matches:
        return default
    longest = len(matches[0][0])
    strongest = {level for prefix, level in matches if len(prefix) == longest}
    if len(strongest) != 1:
        raise RuntimeError("conflicting memory scope rules have the same specificity")
    return next(iter(strongest))


def _consolidation_connection_factory():
    url = os.getenv("CONSOLIDATION_DATABASE_URL", "").strip()
    managed = bool(os.getenv("DECISIONVAULT_SECRET_ARN", "").strip())
    if managed and not url:
        raise RuntimeError("CONSOLIDATION_DATABASE_URL is required in managed mode")
    if url:
        return psycopg_connection_factory(url)
    return psycopg_connection_factory()


def _build_consolidation_outbox() -> ConsolidationOutbox:
    return ConsolidationOutbox(
        connection_factory=_consolidation_connection_factory(),
        lease_seconds=max(30, int(os.getenv("CONSOLIDATION_LEASE_SECONDS", "120"))),
    )


def _memory_quality_calibration_settings() -> tuple[int, int, float, float]:
    lookback_days = int(
        os.getenv(
            "MEMORY_QUALITY_CALIBRATION_LOOKBACK_DAYS",
            str(DEFAULT_CALIBRATION_LOOKBACK_DAYS),
        )
    )
    minimum_samples = int(
        os.getenv(
            "MEMORY_QUALITY_CALIBRATION_MINIMUM_SAMPLES",
            str(DEFAULT_CALIBRATION_MINIMUM_SAMPLES),
        )
    )
    minimum_success_retention = float(
        os.getenv(
            "MEMORY_QUALITY_CALIBRATION_MINIMUM_SUCCESS_RETENTION",
            str(DEFAULT_CALIBRATION_MINIMUM_SUCCESS_RETENTION),
        )
    )
    maximum_harmful_rate = float(
        os.getenv(
            "MEMORY_QUALITY_CALIBRATION_MAXIMUM_HARMFUL_RATE",
            str(DEFAULT_CALIBRATION_MAXIMUM_HARMFUL_RATE),
        )
    )
    if lookback_days <= 0:
        raise RuntimeError("memory-quality calibration lookback must be positive")
    if minimum_samples <= 0:
        raise RuntimeError("memory-quality calibration sample floor must be positive")
    if not 0.0 <= minimum_success_retention <= 1.0:
        raise RuntimeError("memory-quality calibration success retention is invalid")
    if not 0.0 <= maximum_harmful_rate <= 1.0:
        raise RuntimeError("memory-quality calibration harmful-rate gate is invalid")
    return (
        lookback_days,
        minimum_samples,
        minimum_success_retention,
        maximum_harmful_rate,
    )


def _memory_quality_calibration_interval_hours() -> int:
    value = int(
        os.getenv(
            "MEMORY_QUALITY_CALIBRATION_INTERVAL_HOURS",
            str(DEFAULT_CALIBRATION_INTERVAL_HOURS),
        )
    )
    if value <= 0:
        raise RuntimeError("memory-quality calibration interval must be positive")
    return value


def _run_memory_quality_calibration() -> dict[str, Any]:
    (
        lookback_days,
        minimum_samples,
        minimum_success_retention,
        maximum_harmful_rate,
    ) = _memory_quality_calibration_settings()
    try:
        run = run_persisted_calibration(
            connection_factory=psycopg_connection_factory(),
            source="AGENT_API",
            lookback_days=lookback_days,
            minimum_samples=minimum_samples,
            minimum_success_retention=minimum_success_retention,
            maximum_harmful_rate=maximum_harmful_rate,
        )
    except Exception:
        try:
            emit_memory_metric(
                event_name="memory_quality_calibration_failure",
                quality_calibration_failure=1,
            )
        except Exception:
            pass
        raise
    try:
        emit_memory_metric(
            event_name="memory_quality_calibration_run",
            quality_calibration_run=1,
            quality_calibration_samples=run.summary.observed_samples,
            quality_calibration_recommendation=int(
                run.summary.recommendation == "RECOMMEND_CHALLENGER_SHADOW_ONLY"
            ),
        )
    except Exception:
        pass
    return {
        "run_id": run.run_id,
        "source": run.source,
        "decision_rows": run.decision_rows,
        "labeled_outcomes": run.labeled_outcomes,
        "observed_samples": run.summary.observed_samples,
        "recommendation": run.summary.recommendation,
        "recommended_profile": run.summary.recommended_profile,
        "sampling_gate_pass": run.summary.sampling_gate_pass,
        "sampling_blockers": list(run.summary.sampling_audit.get("blockers", ())),
        "minimum_samples": minimum_samples,
        "minimum_success_retention": minimum_success_retention,
        "maximum_harmful_rate": maximum_harmful_rate,
    }


def _maybe_run_memory_quality_calibration() -> dict[str, Any]:
    interval_hours = _memory_quality_calibration_interval_hours()
    connection_factory = psycopg_connection_factory()
    if not calibration_is_due(
        connection_factory=connection_factory,
        source="AGENT_API",
        interval_hours=interval_hours,
    ):
        return {
            "status": "NOT_DUE",
            "interval_hours": interval_hours,
        }
    retention = purge_memory_quality_retention(
        connection_factory=_consolidation_connection_factory(),
        raw_retention_days=DEFAULT_MEMORY_QUALITY_RAW_RETENTION_DAYS,
        calibration_run_retention_days=(
            DEFAULT_MEMORY_QUALITY_CALIBRATION_RUN_RETENTION_DAYS
        ),
    )
    result = _run_memory_quality_calibration()
    return {
        "status": "COMPLETE",
        "interval_hours": interval_hours,
        "retention": retention,
        **result,
    }


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
            scope_level_resolver=_memory_scope_level,
        )
    else:
        store = CockroachVectorMemoryStore(
            connection_factory=psycopg_connection_factory(),
            embedder=deterministic_text_embedding,
            scope_level_resolver=_memory_scope_level,
        )
    return store


def _build_consolidation_service() -> CockroachMemoryConsolidationService:
    store = _build_memory_store()
    if store.semantic_embedder is None or not (store.semantic_embedding_space or "").strip():
        raise RuntimeError("semantic embedding is required for adaptive consolidation")
    return CockroachMemoryConsolidationService(
        connection_factory=_consolidation_connection_factory(),
        semantic_embedder=store.semantic_embedder,
        semantic_embedding_space=str(store.semantic_embedding_space),
    )


def _consolidate_scope(
    scope_id: str,
    *,
    scope_level: MemoryScopeLevel | None = None,
) -> dict[str, Any]:
    resolved_scope_level = scope_level or _memory_scope_level(scope_id)
    active_producers = set(_producer_trust_registry())
    result = _build_consolidation_service().consolidate_scope(
        scope_id=scope_id,
        scope_level=resolved_scope_level,
        active_producer_agent_ids=active_producers,
    )
    return {
        "status": "COMPLETE",
        "scope_level": resolved_scope_level.value,
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

    outbox = _build_consolidation_outbox()
    try:
        work = outbox.claim_scope(scope_id)
    except Exception as exc:
        return {
            "status": "DEFERRED",
            "candidate_count": 0,
            "promoted_count": 0,
            "abstained_count": 0,
            "memory_ids": [],
            "resolutions": [f"OUTBOX_CLAIM_DEFERRED:{type(exc).__name__}"],
            "governance_revision": ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
        }
    if work is None:
        return {
            "status": "DEFERRED",
            "candidate_count": 0,
            "promoted_count": 0,
            "abstained_count": 0,
            "memory_ids": [],
            "resolutions": ["CONSOLIDATION_RETRY_ALREADY_SCHEDULED"],
            "governance_revision": ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
        }
    try:
        result = _consolidate_scope(scope_id, scope_level=work.scope_level)
        outbox.mark_complete(scope_id, generation=work.generation)
        try:
            emit_memory_metric(
                event_name="consolidation_complete",
                consolidation_completed=1,
                promoted=result["promoted_count"],
                abstained=result["abstained_count"],
                outbox_backlog=outbox.backlog_count(),
            )
        except Exception:
            pass
        return result
    except Exception as exc:
        backoff = outbox.mark_deferred(
            scope_id=scope_id,
            error_code=type(exc).__name__,
            attempt_count=work.attempt_count,
            generation=work.generation,
        )
        try:
            emit_memory_metric(
                event_name="consolidation_deferred",
                consolidation_deferred=1,
                outbox_backlog=outbox.backlog_count(),
            )
        except Exception:
            pass
        return {
            "status": "DEFERRED",
            "scope_level": work.scope_level.value,
            "candidate_count": 0,
            "promoted_count": 0,
            "abstained_count": 0,
            "memory_ids": [],
            "retry_after_seconds": backoff,
            "resolutions": [f"CONSOLIDATION_DEFERRED:{type(exc).__name__}"],
            "governance_revision": ADAPTIVE_MEMORY_GOVERNANCE_REVISION,
        }


def _drain_consolidation_outbox(*, limit: int | None = None) -> dict[str, Any]:
    outbox = _build_consolidation_outbox()
    batch_size = max(
        1,
        min(
            50,
            int(
                limit
                if limit is not None
                else os.getenv("CONSOLIDATION_RETRY_BATCH_SIZE", "10")
            ),
        ),
    )
    work_items = outbox.claim_due(limit=batch_size)
    completed = 0
    deferred = 0
    promoted = 0
    abstained = 0
    for work in work_items:
        try:
            result = _consolidate_scope(
                work.scope_id,
                scope_level=work.scope_level,
            )
            outbox.mark_complete(work.scope_id, generation=work.generation)
            completed += 1
            promoted += int(result["promoted_count"])
            abstained += int(result["abstained_count"])
        except Exception as exc:
            outbox.mark_deferred(
                scope_id=work.scope_id,
                error_code=type(exc).__name__,
                attempt_count=work.attempt_count,
                generation=work.generation,
            )
            deferred += 1
    backlog = outbox.backlog_count()
    try:
        emit_memory_metric(
            event_name="consolidation_retry_drain",
            consolidation_completed=completed,
            consolidation_deferred=deferred,
            promoted=promoted,
            abstained=abstained,
            outbox_backlog=backlog,
        )
    except Exception:
        pass
    return {
        "status": "COMPLETE",
        "claimed": len(work_items),
        "completed": completed,
        "deferred": deferred,
        "promoted": promoted,
        "abstained": abstained,
        "backlog": backlog,
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
    adaptive_conn = _consolidation_connection_factory()()
    try:
        with adaptive_conn.cursor() as cur:
            cur.execute(
                "DELETE FROM decision_memory_consolidation_outbox WHERE scope_id = %s",
                (scope_id,),
            )
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
        adaptive_conn.commit()
    finally:
        adaptive_conn.close()

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
        "consolidation_database_configured": bool(
            os.getenv("CONSOLIDATION_DATABASE_URL", "").strip()
        ),
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
    consolidation_database_ok = False
    consolidation_identity_isolated = False
    consolidation_outbox_schema_ok = False
    memory_scope_control_ok = False
    semantic_embedding_ok = False
    semantic_embedding_revision_ok = False
    nvidia_provider_origin_ok = False
    semantic_head_space_ok = False
    governance_schema_ok = False
    adaptive_memory_schema_ok = False
    adaptive_memory_current_ok = False
    memory_quality_telemetry_schema_ok = False
    memory_quality_calibration_schema_ok = False
    memory_quality_calibration_config_ok = False
    agent_auth_ok = False
    receipt_signing_ok = False
    demo_auth_ok = False
    sandbox_config_ok = False
    configured_embedding_space: str | None = None
    runtime_database_user: str | None = None
    errors: list[str] = []

    try:
        hydrate_runtime_secrets()
        secret_ok = True
    except Exception as exc:
        errors.append(f"secrets:{type(exc).__name__}")
        try:
            emit_memory_metric(
                event_name="secret_refresh_failure",
                secret_refresh_failure=1,
            )
        except Exception:
            pass

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

        try:
            _memory_scope_rules()
            memory_scope_control_ok = True
        except Exception as exc:
            errors.append(f"memory_scope_control:{type(exc).__name__}")

        try:
            _memory_quality_calibration_settings()
            _memory_quality_calibration_interval_hours()
            memory_quality_calibration_config_ok = True
        except Exception as exc:
            errors.append(f"memory_quality_calibration_config:{type(exc).__name__}")

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
                    cur.execute("SELECT current_user")
                    runtime_database_user = str(cur.fetchone()[0])
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
                    cur.execute(
                        """
                        SELECT scope_id, scope_level, status, attempt_count, generation,
                               next_attempt_at, lease_until, last_error_code
                        FROM decision_memory_consolidation_outbox LIMIT 0
                        """
                    )
                    consolidation_outbox_schema_ok = True
                    cur.execute(
                        """
                        SELECT decision_snapshot_id, source, decided_at, scope_level,
                               selected_strategy, executable, memory_influenced,
                               memory_resolution, memory_conflict, quality_features,
                               telemetry_revision
                        FROM decision_memory_quality_decisions LIMIT 0
                        """
                    )
                    cur.execute(
                        """
                        SELECT decision_snapshot_id, execution_receipt_id, outcome,
                               effectiveness, confidence, observed_at, recorded_at,
                               telemetry_revision
                        FROM decision_memory_quality_outcomes LIMIT 0
                        """
                    )
                    memory_quality_telemetry_schema_ok = True
                    cur.execute(
                        """
                        SELECT run_id, source, calibration_revision, lookback_days,
                               minimum_samples, minimum_success_retention,
                               maximum_harmful_rate, decision_rows, labeled_outcomes,
                               observed_samples, champion_successes, champion_harmful,
                               recommendation, recommended_profile, challengers,
                               sampling_gate_pass, sampling_audit,
                               generated_at
                        FROM decision_memory_quality_calibration_runs LIMIT 0
                        """
                    )
                    memory_quality_calibration_schema_ok = True
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
            consolidation_conn = _consolidation_connection_factory()()
            try:
                with consolidation_conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    consolidation_database_ok = cur.fetchone()[0] == 1
                    cur.execute("SELECT current_user")
                    consolidation_user = str(cur.fetchone()[0])
                    managed = bool(os.getenv("DECISIONVAULT_SECRET_ARN", "").strip())
                    consolidation_identity_isolated = (
                        not managed
                        or (
                            bool(runtime_database_user)
                            and consolidation_user != runtime_database_user
                        )
                    )
                    if not consolidation_identity_isolated:
                        raise RuntimeError(
                            "runtime and consolidation database identities must differ"
                        )
                    cur.execute(
                        "SELECT scope_id FROM decision_memory_consolidation_outbox LIMIT 0"
                    )
                    cur.execute(
                        "SELECT candidate_id FROM decision_memory_consolidation_candidates LIMIT 0"
                    )
            finally:
                consolidation_conn.close()
        except Exception as exc:
            errors.append(f"consolidation_database:{type(exc).__name__}")

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
            consolidation_database_ok,
            consolidation_identity_isolated,
            consolidation_outbox_schema_ok,
            memory_scope_control_ok,
            governance_schema_ok,
            adaptive_memory_schema_ok,
            adaptive_memory_current_ok,
            memory_quality_telemetry_schema_ok,
            memory_quality_calibration_schema_ok,
            memory_quality_calibration_config_ok,
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
            "consolidation_database": consolidation_database_ok,
            "consolidation_identity_isolated": consolidation_identity_isolated,
            "consolidation_outbox_schema": consolidation_outbox_schema_ok,
            "memory_scope_control": memory_scope_control_ok,
            "memory_governance_schema": governance_schema_ok,
            "adaptive_memory_schema": adaptive_memory_schema_ok,
            "adaptive_memory_current": adaptive_memory_current_ok,
            "memory_quality_telemetry_schema": memory_quality_telemetry_schema_ok,
            "memory_quality_calibration_schema": memory_quality_calibration_schema_ok,
            "memory_quality_calibration_config": memory_quality_calibration_config_ok,
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
        signing_key_id, signing_secret, _ = _execution_signing_material()
        snapshot = issue_decision_snapshot(
            scope_id=scope_id,
            agent_id=agent_id,
            situation=situation,
            strategy=decision.strategy,
            decision_digest=digest,
            decision_provenance=decision_provenance_payload(decision),
            signing_secret=signing_secret,
            signing_key_id=signing_key_id,
        )
        payload["decision_snapshot"] = snapshot
        try:
            insert_decision_quality_event(
                connection_factory=psycopg_connection_factory(),
                decision_snapshot_id=str(snapshot["snapshot_id"]),
                source="AGENT_API",
                decision=decision,
                scope_level=_memory_scope_level(scope_id).value,
                decided_at=datetime.fromisoformat(str(snapshot["issued_at"])),
            )
            emit_memory_metric(
                event_name="memory_quality_decision_observed",
                quality_decision_observed=1,
            )
        except Exception:
            try:
                emit_memory_metric(
                    event_name="memory_quality_decision_write_failure",
                    quality_decision_write_failure=1,
                )
            except Exception:
                pass
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
    signing_key_id, signing_secret, verification_secrets = _execution_signing_material()
    snapshot = verify_decision_snapshot(
        body.get("decision_snapshot"),
        signing_secret=signing_secret,
        verification_secrets=verification_secrets,
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
        signing_secret=signing_secret,
        signing_key_id=signing_key_id,
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


def _best_effort_record_quality_outcome(
    receipt: Any,
    *,
    recorded_at: datetime,
) -> None:
    snapshot_id = str(receipt.decision_snapshot_id or "").strip()
    if not snapshot_id:
        return
    try:
        insert_outcome_quality_event(
            connection_factory=psycopg_connection_factory(),
            decision_snapshot_id=snapshot_id,
            execution_receipt_id=receipt.receipt_id,
            outcome=receipt.outcome,
            effectiveness=receipt.effectiveness,
            confidence=receipt.confidence,
            observed_at=receipt.issued_at,
            recorded_at=recorded_at,
        )
        emit_memory_metric(
            event_name="memory_quality_outcome_observed",
            quality_outcome_observed=1,
        )
    except Exception:
        try:
            emit_memory_metric(
                event_name="memory_quality_outcome_write_failure",
                quality_outcome_write_failure=1,
            )
        except Exception:
            pass


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
    _, signing_secret, verification_secrets = _execution_signing_material()
    receipt = verify_execution_receipt(
        body.get("execution_receipt"),
        signing_secret=signing_secret,
        verification_secrets=verification_secrets,
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
        recorded_at_raw = existing.get("recorded_at")
        recorded_at = (
            datetime.fromisoformat(str(recorded_at_raw))
            if recorded_at_raw
            else datetime.now(timezone.utc)
        )
        _best_effort_record_quality_outcome(
            receipt,
            recorded_at=recorded_at,
        )
        return existing
    receipt = verify_execution_receipt(
        body.get("execution_receipt"),
        signing_secret=signing_secret,
        verification_secrets=verification_secrets,
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
    _best_effort_record_quality_outcome(receipt, recorded_at=episode.recorded_at)
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
        if (
            event.get("source") == "aws.events"
            and event.get("detail-type") == "Scheduled Event"
        ):
            _refresh_runtime_security_state()
            detail = event.get("detail") or {}
            task = str(detail.get("task", "consolidation-retry")).strip()
            if task == "memory-quality-calibration":
                return _json_response(
                    200,
                    {
                        "service": "decisionvault",
                        "scheduled": "memory-quality-calibration",
                        "result": _run_memory_quality_calibration(),
                    },
                )
            if task != "consolidation-retry":
                return _json_response(
                    400,
                    {
                        "service": "decisionvault",
                        "error": "unknown_scheduled_task",
                    },
                )
            consolidation_result = _drain_consolidation_outbox()
            return _json_response(
                200,
                {
                    "service": "decisionvault",
                    "scheduled": "consolidation-retry",
                    "result": consolidation_result,
                    "memory_quality_calibration": (
                        _maybe_run_memory_quality_calibration()
                    ),
                },
            )
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
        if (
            method == "POST"
            and path in {"/decide", "/execute", "/record", "/revoke"}
            and "memory_scope_level" in body
        ):
            return _json_response(
                400,
                {"error": "memory_scope_level_is_server_bound"},
            )
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


def _emit_response_memory_metrics(route: str, response: dict[str, Any]) -> None:
    try:
        payload = json.loads(response.get("body") or "{}")
    except (TypeError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    decision: dict[str, Any]
    if route == "/demo":
        candidate = payload.get("memory_on") or {}
        decision = candidate if isinstance(candidate, dict) else {}
    elif route == "/governance-demo":
        candidate = payload.get("decision") or {}
        decision = candidate if isinstance(candidate, dict) else {}
    else:
        decision = payload
    resolution = str(decision.get("memory_resolution", ""))
    recalled_memory_ids = decision.get("recalled_memory_ids") or []
    emit_memory_metric(
        event_name="decision_memory_resolution",
        negative_veto=int(resolution.startswith("NEGATIVE_MEMORY_VETO")),
        cross_layer_conflict=int(resolution == "CROSS_LAYER_CONFLICT_ABSTAIN"),
        adaptive_hit=int(bool(recalled_memory_ids)),
    )


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    started = time.monotonic()
    response = _handle_request(event, context)
    try:
        route = (
            "scheduled-consolidation"
            if event.get("source") == "aws.events"
            else (str(event.get("rawPath", "/")).rstrip("/") or "/")
        )
        influenced, conflict, replay = _response_metric_flags(route, response)
        emit_request_metric(
            route=route,
            status_code=int(response.get("statusCode", 500)),
            latency_ms=(time.monotonic() - started) * 1000.0,
            memory_influenced=influenced,
            memory_conflict=conflict,
            idempotent_replay=replay,
        )
        _emit_response_memory_metrics(route, response)
    except Exception:
        # Observability is non-authoritative and cannot change the API result.
        pass
    return response
