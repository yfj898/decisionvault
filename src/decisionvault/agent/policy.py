from __future__ import annotations

from decisionvault.domain import Decision, Outcome, RecalledEpisode, Strategy


class OutcomeAwarePolicy:
    """Small deterministic policy that makes the memory effect auditable."""

    def decide(
        self,
        *,
        recalled: list[RecalledEpisode],
    ) -> Decision:
        relevant = [item for item in recalled if item.similarity >= 0.30]

        successful = [
            item
            for item in relevant
            if item.episode.outcome == Outcome.SUCCESS
            and item.episode.effectiveness >= 0.7
        ]
        if successful:
            best = max(
                successful,
                key=lambda item: (
                    item.similarity,
                    item.episode.effectiveness,
                    item.episode.confidence,
                ),
            )
            return Decision(
                strategy=best.episode.strategy,
                reason=(
                    f"reused successful strategy {best.episode.strategy.value} "
                    f"from episode {best.episode.episode_id}"
                ),
                recalled_episode_ids=(best.episode.episode_id,),
                memory_influenced=True,
            )

        failed_generic = [
            item
            for item in relevant
            if item.episode.strategy == Strategy.GENERIC_RETRY
            and item.episode.outcome == Outcome.FAILED
            and item.episode.confidence >= 0.6
        ]
        if failed_generic:
            best = max(failed_generic, key=lambda item: item.similarity)
            return Decision(
                strategy=Strategy.REFRESH_PAYMENT_TOKEN,
                reason=(
                    "avoided GENERIC_RETRY because a similar remembered "
                    f"episode failed: {best.episode.episode_id}"
                ),
                recalled_episode_ids=(best.episode.episode_id,),
                memory_influenced=True,
            )

        return Decision(
            strategy=Strategy.GENERIC_RETRY,
            reason="no sufficiently relevant outcome memory; use safe default",
            memory_influenced=False,
        )
