from __future__ import annotations

from pathlib import Path

import pytest

import decisionvault.aws_lambda as aws_lambda


ROOT = Path(__file__).resolve().parents[1]
TARGET = "00000000-0000-0000-0000-000000000123"


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.executions = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executions.append((sql, params))

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row):
        self.cursor_value = FakeCursor(row)

    def cursor(self):
        return self.cursor_value

    def close(self):
        pass


def _set_target(monkeypatch, row):
    conn = FakeConnection(row)
    monkeypatch.setattr(
        aws_lambda,
        "psycopg_connection_factory",
        lambda: (lambda: conn),
    )
    return conn


def test_supersession_requires_same_producer_and_current_head(monkeypatch):
    _set_target(monkeypatch, ("agent-a", True))
    assert aws_lambda._validate_supersession(
        scope_id="scope-a",
        agent_id="agent-a",
        supersedes_episode_id=TARGET,
    ) == TARGET


def test_supersession_rejects_cross_producer(monkeypatch):
    _set_target(monkeypatch, ("agent-b", True))
    with pytest.raises(ValueError, match="only its own"):
        aws_lambda._validate_supersession(
            scope_id="scope-a",
            agent_id="agent-a",
            supersedes_episode_id=TARGET,
        )


def test_supersession_rejects_non_current_target(monkeypatch):
    _set_target(monkeypatch, ("agent-a", False))
    with pytest.raises(aws_lambda.SupersessionConflict, match="current governed head"):
        aws_lambda._validate_supersession(
            scope_id="scope-a",
            agent_id="agent-a",
            supersedes_episode_id=TARGET,
        )


def test_supersession_rejects_missing_target(monkeypatch):
    _set_target(monkeypatch, None)
    with pytest.raises(ValueError, match="does not exist"):
        aws_lambda._validate_supersession(
            scope_id="scope-a",
            agent_id="agent-a",
            supersedes_episode_id=TARGET,
        )


def test_supersession_schema_is_typed_and_unique():
    sql = (ROOT / "scripts" / "supersession.sql").read_text(encoding="utf-8")
    assert "supersedes_episode_id UUID" in sql
    assert "decision_episodes_supersedes_uidx" in sql
    assert "WHERE supersedes_episode_id IS NOT NULL" in sql
