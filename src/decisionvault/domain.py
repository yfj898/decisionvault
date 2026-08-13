from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Mapping


class Strategy(StrEnum):
    GENERIC_RETRY = "GENERIC_RETRY"
    REFRESH_PAYMENT_TOKEN = "REFRESH_PAYMENT_TOKEN"
    VERIFY_BILLING_PROFILE = "VERIFY_BILLING_PROFILE"


class Outcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class DecisionEpisode:
    episode_id: str
    scope_id: str
    situation: str
    strategy: Strategy
    outcome: Outcome
    effectiveness: float
    confidence: float
    evidence: Mapping[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.episode_id:
            raise ValueError("episode_id is required")
        if not self.scope_id:
            raise ValueError("scope_id is required")
        if not self.situation.strip():
            raise ValueError("situation is required")
        if not 0 <= self.effectiveness <= 1:
            raise ValueError("effectiveness must be between 0 and 1")
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RecalledEpisode:
    episode: DecisionEpisode
    similarity: float

    def __post_init__(self) -> None:
        if not 0 <= self.similarity <= 1:
            raise ValueError("similarity must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class Decision:
    strategy: Strategy
    reason: str
    recalled_episode_ids: tuple[str, ...] = ()
    recalled_producer_agent_ids: tuple[str, ...] = ()
    memory_influenced: bool = False
    model_explanation: str | None = None
    model_provider: str | None = None
