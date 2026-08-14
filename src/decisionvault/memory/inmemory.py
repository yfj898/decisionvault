from __future__ import annotations

import re

from decisionvault.domain import DecisionEpisode, RecalledEpisode


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2
    }


def _similarity(left: str, right: str) -> float:
    a = _tokens(left)
    b = _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class InMemoryEpisodeStore:
    """Deterministic development store used only for offline tests."""

    def __init__(self) -> None:
        self._episodes: list[DecisionEpisode] = []

    def save(self, episode: DecisionEpisode) -> None:
        self._episodes.append(episode)

    def recall(
        self,
        *,
        scope_id: str,
        situation: str,
        limit: int = 5,
    ) -> list[RecalledEpisode]:
        matches = [
            RecalledEpisode(
                episode=episode,
                similarity=_similarity(situation, episode.situation),
            )
            for episode in self._episodes
            if episode.scope_id == scope_id
        ]
        matches = [match for match in matches if match.similarity > 0]
        matches.sort(
            key=lambda match: (
                match.similarity,
                match.episode.confidence,
                match.episode.created_at,
            ),
            reverse=True,
        )
        return matches[:limit]

    def recall_governed(
        self,
        *,
        scope_id: str,
        situation: str,
        minimum_similarity: float,
    ) -> list[RecalledEpisode]:
        matches = [
            RecalledEpisode(
                episode=episode,
                similarity=_similarity(situation, episode.situation),
            )
            for episode in self._episodes
            if episode.scope_id == scope_id
        ]
        matches = [
            match for match in matches if match.similarity >= minimum_similarity
        ]
        matches.sort(
            key=lambda match: (
                match.similarity,
                match.episode.confidence,
                match.episode.created_at,
            ),
            reverse=True,
        )
        return matches

    @property
    def episodes(self) -> tuple[DecisionEpisode, ...]:
        return tuple(self._episodes)
