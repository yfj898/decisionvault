from __future__ import annotations

from typing import Protocol

from decisionvault.domain import Decision, RecalledEpisode


class DecisionAdvisor(Protocol):
    """Untrusted explanation-only model interface.

    Advisors receive the already-committed deterministic decision and recalled
    memory evidence. They can explain that decision, but the interface gives
    them no way to return or replace a Strategy.
    """

    @property
    def provider_name(self) -> str: ...

    def explain(
        self,
        *,
        situation: str,
        decision: Decision,
        recalled: list[RecalledEpisode],
    ) -> str: ...
