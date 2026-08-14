from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid4, uuid5

from decisionvault.domain import Decision, Outcome, Strategy


RECEIPT_VERSION = 2
LEGACY_RECEIPT_VERSION = 1
DEFAULT_RECEIPT_TTL_SECONDS = 900
DECISION_SNAPSHOT_VERSION = 1
DECISION_SNAPSHOT_TTL_SECONDS = 300
DECISION_CONTRACT_REVISION = "governed-adaptive-memory-v2"


SANDBOX_OUTCOMES: dict[str, dict[Strategy, tuple[Outcome, float]]] = {
    "stale_payment_token": {
        Strategy.GENERIC_RETRY: (Outcome.FAILED, 0.10),
        Strategy.REFRESH_PAYMENT_TOKEN: (Outcome.SUCCESS, 0.95),
        Strategy.VERIFY_BILLING_PROFILE: (Outcome.FAILED, 0.20),
    },
    "billing_profile_mismatch": {
        Strategy.GENERIC_RETRY: (Outcome.FAILED, 0.10),
        Strategy.REFRESH_PAYMENT_TOKEN: (Outcome.FAILED, 0.20),
        Strategy.VERIFY_BILLING_PROFILE: (Outcome.SUCCESS, 0.95),
    },
    "transient_issuer_outage": {
        Strategy.GENERIC_RETRY: (Outcome.SUCCESS, 0.90),
        Strategy.REFRESH_PAYMENT_TOKEN: (Outcome.FAILED, 0.20),
        Strategy.VERIFY_BILLING_PROFILE: (Outcome.FAILED, 0.20),
    },
}


def configured_sandbox_scenario(value: str | None) -> str:
    """Validate the server-owned sandbox scenario.

    General agents never choose this value in an execution request. The hosted
    sandbox binds it from server configuration so a caller cannot obtain a
    signed outcome merely by self-asserting a different scenario label.
    """

    scenario = (value or "stale_payment_token").strip()
    if scenario not in SANDBOX_OUTCOMES:
        raise ValueError(f"unsupported server sandbox scenario: {scenario}")
    return scenario


@dataclass(frozen=True, slots=True)
class VerifiedExecutionReceipt:
    version: int
    receipt_id: str
    scope_id: str
    agent_id: str
    situation: str
    strategy: Strategy
    scenario: str
    outcome: Outcome
    effectiveness: float
    confidence: float
    issued_at: datetime
    signature: str
    decision_snapshot_id: str | None = None
    decision_digest: str | None = None
    decision_revision: str | None = None
    decision_agent_id: str | None = None
    decision_provenance: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class VerifiedDecisionSnapshot:
    version: int
    snapshot_id: str
    scope_id: str
    agent_id: str
    situation: str
    strategy: Strategy
    decision_digest: str
    decision_revision: str
    issued_at: datetime
    signature: str
    decision_provenance: Mapping[str, Any]


class DecisionSnapshotStale(RuntimeError):
    """A previously issued decision snapshot is no longer executable."""


def _canonical_payload(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sign(payload: dict[str, Any], secret: str) -> str:
    if len(secret) < 16:
        raise ValueError("execution receipt signing secret is too short")
    return hmac.new(
        secret.encode("utf-8"),
        _canonical_payload(payload),
        sha256,
    ).hexdigest()


def decision_state_digest(
    decision: Decision,
    *,
    semantic_embedding_space: str,
    decision_revision: str = DECISION_CONTRACT_REVISION,
) -> str:
    """Hash only deterministic execution-relevant policy and memory state."""

    payload = {
        "decision_revision": decision_revision,
        "semantic_embedding_space": semantic_embedding_space,
        "action": decision.action.value,
        "strategy": decision.strategy.value if decision.strategy is not None else None,
        "memory_influenced": decision.memory_influenced,
        "memory_resolution": decision.memory_resolution,
        "memory_conflict": decision.memory_conflict,
        "recalled_episode_ids": list(decision.recalled_episode_ids),
        "recalled_memory_ids": list(decision.recalled_memory_ids),
        "recalled_producer_agent_ids": list(decision.recalled_producer_agent_ids),
        "governance_trace": asdict(decision.governance_trace),
    }
    return sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def decision_provenance_payload(decision: Decision) -> dict[str, Any]:
    """Canonical human-auditable provenance committed into signed snapshots."""

    return {
        "recalled_episode_ids": list(decision.recalled_episode_ids),
        "recalled_memory_ids": list(decision.recalled_memory_ids),
        "recalled_producer_agent_ids": list(decision.recalled_producer_agent_ids),
        "memory_resolution": decision.memory_resolution,
        "memory_conflict": decision.memory_conflict,
        "governance_trace": asdict(decision.governance_trace),
    }


def issue_decision_snapshot(
    *,
    scope_id: str,
    agent_id: str,
    situation: str,
    strategy: Strategy,
    decision_digest: str,
    signing_secret: str,
    decision_revision: str = DECISION_CONTRACT_REVISION,
    decision_provenance: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    issued_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload: dict[str, Any] = {
        "version": DECISION_SNAPSHOT_VERSION,
        "snapshot_id": str(uuid4()),
        "scope_id": scope_id,
        "agent_id": agent_id,
        "situation": situation,
        "strategy": strategy.value,
        "decision_digest": decision_digest,
        "decision_revision": decision_revision,
        "decision_provenance": dict(decision_provenance or {}),
        "issued_at": issued_at.isoformat(),
    }
    payload["signature"] = _sign(payload, signing_secret)
    return payload


def verify_decision_snapshot(
    payload: Any,
    *,
    signing_secret: str,
    expected_scope_id: str,
    expected_situation: str,
    expected_strategy: Strategy,
    ttl_seconds: int = DECISION_SNAPSHOT_TTL_SECONDS,
    now: datetime | None = None,
) -> VerifiedDecisionSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("decision_snapshot must be an object")
    signature = str(payload.get("signature", "")).strip()
    if not signature:
        raise ValueError("decision snapshot signature is required")
    if not hmac.compare_digest(signature, _sign(payload, signing_secret)):
        raise ValueError("decision snapshot signature is invalid")
    if int(payload.get("version", 0)) != DECISION_SNAPSHOT_VERSION:
        raise ValueError("unsupported decision snapshot version")

    snapshot_id = str(payload.get("snapshot_id", "")).strip()
    scope_id = str(payload.get("scope_id", "")).strip()
    agent_id = str(payload.get("agent_id", "")).strip()
    situation = str(payload.get("situation", "")).strip()
    decision_digest = str(payload.get("decision_digest", "")).strip()
    decision_revision = str(payload.get("decision_revision", "")).strip()
    if not all((snapshot_id, scope_id, agent_id, situation, decision_digest, decision_revision)):
        raise ValueError("decision snapshot is missing required fields")
    if scope_id != expected_scope_id:
        raise ValueError("decision snapshot scope does not match authenticated request")
    if situation != expected_situation:
        raise ValueError("decision snapshot situation does not match execution request")
    strategy = Strategy(str(payload.get("strategy", "")))
    if strategy != expected_strategy:
        raise ValueError("decision snapshot strategy does not match execution request")
    if decision_revision != DECISION_CONTRACT_REVISION:
        raise DecisionSnapshotStale("decision snapshot revision is no longer current")
    provenance = payload.get("decision_provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("decision snapshot provenance must be an object")

    issued_at = datetime.fromisoformat(str(payload.get("issued_at", "")))
    if issued_at.tzinfo is None:
        raise ValueError("decision snapshot issued_at must be timezone-aware")
    issued_at = issued_at.astimezone(timezone.utc)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if issued_at > current + timedelta(seconds=60):
        raise ValueError("decision snapshot issued_at is in the future")
    if current - issued_at > timedelta(seconds=ttl_seconds):
        raise DecisionSnapshotStale("decision snapshot has expired")

    return VerifiedDecisionSnapshot(
        version=DECISION_SNAPSHOT_VERSION,
        snapshot_id=snapshot_id,
        scope_id=scope_id,
        agent_id=agent_id,
        situation=situation,
        strategy=strategy,
        decision_digest=decision_digest,
        decision_revision=decision_revision,
        issued_at=issued_at,
        signature=signature,
        decision_provenance=provenance,
    )


def issue_sandbox_receipt(
    *,
    scope_id: str,
    agent_id: str,
    situation: str,
    strategy: Strategy,
    scenario: str,
    signing_secret: str,
    decision_snapshot_id: str | None = None,
    decision_digest: str | None = None,
    decision_revision: str | None = None,
    decision_agent_id: str | None = None,
    decision_provenance: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    scenario_outcomes = SANDBOX_OUTCOMES.get(scenario)
    if scenario_outcomes is None:
        raise ValueError(f"unsupported sandbox scenario: {scenario}")
    outcome, effectiveness = scenario_outcomes[strategy]
    issued_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    receipt_id = (
        str(uuid5(NAMESPACE_URL, f"decisionvault-sandbox:{decision_snapshot_id}"))
        if decision_snapshot_id
        else str(uuid4())
    )
    payload: dict[str, Any] = {
        "version": RECEIPT_VERSION if decision_snapshot_id else LEGACY_RECEIPT_VERSION,
        "receipt_id": receipt_id,
        "scope_id": scope_id,
        "agent_id": agent_id,
        "situation": situation,
        "strategy": strategy.value,
        "scenario": scenario,
        "outcome": outcome.value,
        "effectiveness": effectiveness,
        "confidence": 1.0,
        "issued_at": issued_at.isoformat(),
    }
    if decision_snapshot_id:
        if not decision_digest or not decision_revision or not decision_agent_id:
            raise ValueError("snapshot-bound receipt requires decision digest/revision")
        payload.update(
            {
                "decision_snapshot_id": decision_snapshot_id,
                "decision_digest": decision_digest,
                "decision_revision": decision_revision,
                "decision_agent_id": decision_agent_id,
                "decision_provenance": dict(decision_provenance or {}),
            }
        )
    payload["signature"] = _sign(payload, signing_secret)
    return payload


def verify_execution_receipt(
    payload: Any,
    *,
    signing_secret: str,
    expected_scope_id: str,
    expected_agent_id: str,
    ttl_seconds: int | None = DEFAULT_RECEIPT_TTL_SECONDS,
    now: datetime | None = None,
) -> VerifiedExecutionReceipt:
    if not isinstance(payload, dict):
        raise ValueError("execution_receipt must be an object")
    signature = str(payload.get("signature", "")).strip()
    if not signature:
        raise ValueError("execution receipt signature is required")
    expected_signature = _sign(payload, signing_secret)
    if not hmac.compare_digest(signature, expected_signature):
        raise ValueError("execution receipt signature is invalid")

    version = int(payload.get("version", 0))
    if version not in {LEGACY_RECEIPT_VERSION, RECEIPT_VERSION}:
        raise ValueError("unsupported execution receipt version")

    scope_id = str(payload.get("scope_id", "")).strip()
    agent_id = str(payload.get("agent_id", "")).strip()
    if scope_id != expected_scope_id:
        raise ValueError("execution receipt scope does not match authenticated request")
    if agent_id != expected_agent_id:
        raise ValueError("execution receipt agent does not match authenticated request")

    situation = str(payload.get("situation", "")).strip()
    scenario = str(payload.get("scenario", "")).strip()
    receipt_id = str(payload.get("receipt_id", "")).strip()
    if not situation or not scenario or not receipt_id:
        raise ValueError("execution receipt is missing required fields")

    issued_at = datetime.fromisoformat(str(payload.get("issued_at", "")))
    if issued_at.tzinfo is None:
        raise ValueError("execution receipt issued_at must be timezone-aware")
    issued_at = issued_at.astimezone(timezone.utc)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if issued_at > current + timedelta(seconds=60):
        raise ValueError("execution receipt issued_at is in the future")
    if ttl_seconds is not None and current - issued_at > timedelta(seconds=ttl_seconds):
        raise ValueError("execution receipt has expired")

    strategy = Strategy(str(payload.get("strategy", "")))
    outcome = Outcome(str(payload.get("outcome", "")))
    effectiveness = float(payload.get("effectiveness"))
    confidence = float(payload.get("confidence", 1.0))
    if not 0.0 <= effectiveness <= 1.0 or not 0.0 <= confidence <= 1.0:
        raise ValueError("execution receipt scores must be between 0 and 1")

    scenario_outcomes = SANDBOX_OUTCOMES.get(scenario)
    if scenario_outcomes is None:
        raise ValueError("execution receipt scenario is unsupported")
    expected_outcome, expected_effectiveness = scenario_outcomes[strategy]
    if outcome != expected_outcome or abs(effectiveness - expected_effectiveness) > 1e-9:
        raise ValueError("execution receipt outcome does not match sandbox scenario")

    decision_snapshot_id = str(payload.get("decision_snapshot_id", "")).strip() or None
    decision_digest = str(payload.get("decision_digest", "")).strip() or None
    decision_revision = str(payload.get("decision_revision", "")).strip() or None
    decision_agent_id = str(payload.get("decision_agent_id", "")).strip() or None
    decision_provenance: Mapping[str, Any] | None = None
    if version == RECEIPT_VERSION:
        if not all(
            (decision_snapshot_id, decision_digest, decision_revision, decision_agent_id)
        ):
            raise ValueError("snapshot-bound execution receipt is missing decision binding")
        if decision_revision != DECISION_CONTRACT_REVISION:
            raise ValueError("execution receipt decision revision is unsupported")
        provenance = payload.get("decision_provenance", {})
        if not isinstance(provenance, dict):
            raise ValueError("execution receipt decision_provenance must be an object")
        decision_provenance = provenance

    return VerifiedExecutionReceipt(
        version=version,
        receipt_id=receipt_id,
        scope_id=scope_id,
        agent_id=agent_id,
        situation=situation,
        strategy=strategy,
        scenario=scenario,
        outcome=outcome,
        effectiveness=effectiveness,
        confidence=confidence,
        issued_at=issued_at,
        signature=signature,
        decision_snapshot_id=decision_snapshot_id,
        decision_digest=decision_digest,
        decision_revision=decision_revision,
        decision_agent_id=decision_agent_id,
        decision_provenance=decision_provenance,
    )


def receipt_as_dict(receipt: VerifiedExecutionReceipt) -> dict[str, Any]:
    payload = asdict(receipt)
    payload["strategy"] = receipt.strategy.value
    payload["outcome"] = receipt.outcome.value
    payload["issued_at"] = receipt.issued_at.isoformat()
    return payload
