from datetime import datetime, timezone
import pytest

from decisionvault.domain import DecisionEpisode, Outcome, Strategy


def test_episode_rejects_naive_timestamp():
    with pytest.raises(ValueError, match="timezone-aware"):
        DecisionEpisode(
            episode_id="ep-1",
            scope_id="scope",
            situation="case",
            strategy=Strategy.GENERIC_RETRY,
            outcome=Outcome.FAILED,
            effectiveness=0.1,
            confidence=1.0,
            observed_at=datetime.now(),
        )


def test_episode_rejects_invalid_effectiveness():
    with pytest.raises(ValueError, match="effectiveness"):
        DecisionEpisode(
            episode_id="ep-1",
            scope_id="scope",
            situation="case",
            strategy=Strategy.GENERIC_RETRY,
            outcome=Outcome.FAILED,
            effectiveness=1.1,
            confidence=1.0,
            observed_at=datetime.now(timezone.utc),
        )


def test_episode_rejects_naive_recorded_timestamp():
    with pytest.raises(ValueError, match="recorded_at"):
        DecisionEpisode(
            episode_id="ep-1",
            scope_id="scope",
            situation="case",
            strategy=Strategy.GENERIC_RETRY,
            outcome=Outcome.FAILED,
            effectiveness=0.1,
            confidence=1.0,
            observed_at=datetime.now(timezone.utc),
            recorded_at=datetime.now(),
        )
