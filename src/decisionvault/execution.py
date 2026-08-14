from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
from typing import Any
from uuid import uuid4

from decisionvault.domain import Outcome, Strategy


RECEIPT_VERSION = 1
DEFAULT_RECEIPT_TTL_SECONDS = 900


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


def issue_sandbox_receipt(
    *,
    scope_id: str,
    agent_id: str,
    situation: str,
    strategy: Strategy,
    scenario: str,
    signing_secret: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    scenario_outcomes = SANDBOX_OUTCOMES.get(scenario)
    if scenario_outcomes is None:
        raise ValueError(f"unsupported sandbox scenario: {scenario}")
    outcome, effectiveness = scenario_outcomes[strategy]
    issued_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload: dict[str, Any] = {
        "version": RECEIPT_VERSION,
        "receipt_id": str(uuid4()),
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
    if version != RECEIPT_VERSION:
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
    )


def receipt_as_dict(receipt: VerifiedExecutionReceipt) -> dict[str, Any]:
    payload = asdict(receipt)
    payload["strategy"] = receipt.strategy.value
    payload["outcome"] = receipt.outcome.value
    payload["issued_at"] = receipt.issued_at.isoformat()
    return payload
