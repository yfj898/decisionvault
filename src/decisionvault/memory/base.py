from __future__ import annotations

from typing import Protocol

from decisionvault.domain import DecisionEpisode, RecalledEpisode


class MemoryStore(Protocol):
    def save(self, episode: DecisionEpisode) -> None: ...

    def recall(
        self,
        *,
        scope_id: str,
        situation: str,
        limit: int = 5,
    ) -> list[RecalledEpisode]: ...
