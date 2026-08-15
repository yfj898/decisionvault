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
EXTERNAL_RECEIPT_VERSION = 3
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
    signing_key_id: str | None = None
    decision_snapshot_id: str | None = None
    decision_digest: str | None = None
    decision_revision: str | None = None
    decision_agent_id: str | None = None
    decision_provenance: Mapping[str, Any] | None = None
    execution_provider: str | None = None
    external_operation_id: str | None = None
    execution_evidence: Mapping[str, Any] | None = None


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
    signing_key_id: str | None
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


def _verification_secret(
    payload: Mapping[str, Any],
    *,
    signing_secret: str,
    verification_secrets: Mapping[str, str] | None,
) -> tuple[tuple[str, ...], str | None]:
    """Resolve the exact key bound into a signed artifact.

    Legacy artifacts without a key id continue to verify against the supplied
    current/legacy secret. Keyed artifacts must name a retained verification
    key, so normal rotation cannot silently invalidate historical receipts.
    """

    key_id = str(payload.get("signing_key_id", "")).strip() or None
    if key_id is None:
        candidates = [signing_secret]
        if verification_secrets is not None:
            candidates.extend(str(value) for value in verification_secrets.values())
        return tuple(dict.fromkeys(candidates)), None
    if verification_secrets is None:
        raise ValueError("signed artifact key id is not available for verification")
    secret = str(verification_secrets.get(key_id, ""))
    if len(secret) < 16:
        raise ValueError("signed artifact key id is not available for verification")
    return (secret,), key_id


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
    signing_key_id: str | None = None,
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
    if signing_key_id:
        payload["signing_key_id"] = signing_key_id
    payload["signature"] = _sign(payload, signing_secret)
    return payload


def verify_decision_snapshot(
    payload: Any,
    *,
    signing_secret: str,
    verification_secrets: Mapping[str, str] | None = None,
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
    verification_candidates, signing_key_id = _verification_secret(
        payload,
        signing_secret=signing_secret,
        verification_secrets=verification_secrets,
    )
    if not any(
        hmac.compare_digest(signature, _sign(payload, candidate))
        for candidate in verification_candidates
    ):
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
        signing_key_id=signing_key_id,
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
    signing_key_id: str | None = None,
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
    if signing_key_id:
        payload["signing_key_id"] = signing_key_id
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


def issue_external_receipt(
    *,
    scope_id: str,
    agent_id: str,
    situation: str,
    strategy: Strategy,
    execution_provider: str,
    external_operation_id: str,
    execution_evidence: Mapping[str, Any],
    outcome: Outcome,
    effectiveness: float,
    confidence: float,
    signing_secret: str,
    decision_snapshot_id: str,
    decision_digest: str,
    decision_revision: str,
    decision_agent_id: str,
    decision_provenance: Mapping[str, Any] | None = None,
    signing_key_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Issue a signed receipt for a server-verified external side effect."""

    provider = execution_provider.strip()
    operation_id = external_operation_id.strip()
    if not provider or not operation_id:
        raise ValueError("external receipt provider and operation id are required")
    if not 0.0 <= effectiveness <= 1.0 or not 0.0 <= confidence <= 1.0:
        raise ValueError("external receipt scores must be between 0 and 1")
    if decision_revision != DECISION_CONTRACT_REVISION:
        raise ValueError("external receipt decision revision is unsupported")
    issued_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    receipt_id = str(
        uuid5(
            NAMESPACE_URL,
            f"decisionvault-external:{provider}:{decision_snapshot_id}",
        )
    )
    payload: dict[str, Any] = {
        "version": EXTERNAL_RECEIPT_VERSION,
        "receipt_id": receipt_id,
        "scope_id": scope_id,
        "agent_id": agent_id,
        "situation": situation,
        "strategy": strategy.value,
        "scenario": "external_verified_execution",
        "outcome": outcome.value,
        "effectiveness": float(effectiveness),
        "confidence": float(confidence),
        "execution_provider": provider,
        "external_operation_id": operation_id,
        "execution_evidence": dict(execution_evidence),
        "decision_snapshot_id": decision_snapshot_id,
        "decision_digest": decision_digest,
        "decision_revision": decision_revision,
        "decision_agent_id": decision_agent_id,
        "decision_provenance": dict(decision_provenance or {}),
        "issued_at": issued_at.isoformat(),
    }
    if signing_key_id:
        payload["signing_key_id"] = signing_key_id
    payload["signature"] = _sign(payload, signing_secret)
    return payload


def verify_execution_receipt(
    payload: Any,
    *,
    signing_secret: str,
    verification_secrets: Mapping[str, str] | None = None,
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
    verification_candidates, signing_key_id = _verification_secret(
        payload,
        signing_secret=signing_secret,
        verification_secrets=verification_secrets,
    )
    if not any(
        hmac.compare_digest(signature, _sign(payload, candidate))
        for candidate in verification_candidates
    ):
        raise ValueError("execution receipt signature is invalid")

    version = int(payload.get("version", 0))
    if version not in {
        LEGACY_RECEIPT_VERSION,
        RECEIPT_VERSION,
        EXTERNAL_RECEIPT_VERSION,
    }:
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

    execution_provider: str | None = None
    external_operation_id: str | None = None
    execution_evidence: Mapping[str, Any] | None = None
    if version == EXTERNAL_RECEIPT_VERSION:
        execution_provider = str(payload.get("execution_provider", "")).strip() or None
        external_operation_id = (
            str(payload.get("external_operation_id", "")).strip() or None
        )
        evidence = payload.get("execution_evidence", {})
        if not execution_provider or not external_operation_id:
            raise ValueError("external execution receipt is missing provider binding")
        if not isinstance(evidence, dict) or not bool(evidence.get("verified")):
            raise ValueError("external execution receipt is missing verified evidence")
        execution_evidence = evidence
    else:
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
    if version in {RECEIPT_VERSION, EXTERNAL_RECEIPT_VERSION}:
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
        signing_key_id=signing_key_id,
        decision_snapshot_id=decision_snapshot_id,
        decision_digest=decision_digest,
        decision_revision=decision_revision,
        decision_agent_id=decision_agent_id,
        decision_provenance=decision_provenance,
        execution_provider=execution_provider,
        external_operation_id=external_operation_id,
        execution_evidence=execution_evidence,
    )


def receipt_as_dict(receipt: VerifiedExecutionReceipt) -> dict[str, Any]:
    payload = asdict(receipt)
    payload["strategy"] = receipt.strategy.value
    payload["outcome"] = receipt.outcome.value
    payload["issued_at"] = receipt.issued_at.isoformat()
    return payload
