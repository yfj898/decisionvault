from __future__ import annotations

import base64
from io import BytesIO
import json

import pytest
from urllib.error import HTTPError

from decisionvault.domain import Outcome, Strategy
import decisionvault.execution_adapters as adapters
from decisionvault.execution_adapters import GitHubContentsExecutionAdapter


TOKEN = "test-github-token"
REPO = "yfj898/decisionvault-execution-sandbox"
SNAPSHOT = "00000000-0000-0000-0000-000000000777"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, _limit):
        return json.dumps(self.payload).encode("utf-8")


def _http_error(code: int) -> HTTPError:
    return HTTPError(
        "https://api.github.com/test",
        code,
        "test",
        hdrs=None,
        fp=BytesIO(b"{}"),
    )


def _file(snapshot: str = SNAPSHOT, *, sha: str = "blob-sha-7") -> dict:
    content = GitHubContentsExecutionAdapter._document_bytes(
        snapshot, Strategy.REFRESH_PAYMENT_TOKEN
    )
    return {
        "type": "file",
        "path": GitHubContentsExecutionAdapter._resource_path(snapshot),
        "sha": sha,
        "encoding": "base64",
        "content": base64.b64encode(content).decode("ascii"),
    }


def test_github_contents_adapter_creates_then_reads_back_fixed_resource(monkeypatch):
    calls = []
    responses = iter([_http_error(404), {"commit": {"sha": "commit-1"}}, _file()])

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, request.method, timeout, request.data))
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        return _Response(item)

    monkeypatch.setattr(adapters, "urlopen", fake_urlopen)
    adapter = GitHubContentsExecutionAdapter(token=TOKEN, repository=REPO)
    result = adapter.execute(
        decision_snapshot_id=SNAPSHOT,
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
    )

    assert result.outcome == Outcome.UNKNOWN
    assert result.effectiveness == 0.0
    assert result.evidence["verified"] is True
    assert result.evidence["idempotent_replay"] is False
    assert result.evidence["path"].endswith(f"{SNAPSHOT}.json")
    assert [method for _, method, _, _ in calls] == ["GET", "PUT", "GET"]
    assert all(url.startswith("https://api.github.com/repos/") for url, *_ in calls)
    created = json.loads(calls[1][3])
    decoded = base64.b64decode(created["content"])
    assert b"replacement card" not in decoded
    assert SNAPSHOT.encode() in decoded


def test_github_contents_adapter_replay_never_creates_duplicate(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(request.method)
        return _Response(_file(sha="stable-blob"))

    monkeypatch.setattr(adapters, "urlopen", fake_urlopen)
    result = GitHubContentsExecutionAdapter(token=TOKEN, repository=REPO).execute(
        decision_snapshot_id=SNAPSHOT,
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
    )

    assert calls == ["GET"]
    assert result.evidence["idempotent_replay"] is True
    assert result.external_operation_id.endswith("@stable-blob")


def test_github_contents_adapter_reconciles_timeout_after_success(monkeypatch):
    calls = []
    responses = iter(
        [_http_error(404), TimeoutError("network timeout"), _file(sha="after-timeout")]
    )

    def fake_urlopen(request, timeout):
        calls.append(request.method)
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        return _Response(item)

    monkeypatch.setattr(adapters, "urlopen", fake_urlopen)
    result = GitHubContentsExecutionAdapter(token=TOKEN, repository=REPO).execute(
        decision_snapshot_id=SNAPSHOT,
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
    )

    assert calls == ["GET", "PUT", "GET"]
    assert result.evidence["idempotent_replay"] is True
    assert result.external_operation_id.endswith("@after-timeout")


def test_github_contents_adapter_reconciles_concurrent_create_conflict(monkeypatch):
    calls = []
    responses = iter([_http_error(404), _http_error(422), _file(sha="winner")])

    def fake_urlopen(request, timeout):
        calls.append(request.method)
        item = next(responses)
        if isinstance(item, Exception):
            raise item
        return _Response(item)

    monkeypatch.setattr(adapters, "urlopen", fake_urlopen)
    result = GitHubContentsExecutionAdapter(token=TOKEN, repository=REPO).execute(
        decision_snapshot_id=SNAPSHOT,
        strategy=Strategy.REFRESH_PAYMENT_TOKEN,
    )

    assert calls == ["GET", "PUT", "GET"]
    assert result.evidence["idempotent_replay"] is True
    assert result.external_operation_id.endswith("@winner")


def test_github_contents_adapter_rejects_non_repository_target():
    with pytest.raises(ValueError, match="owner/name"):
        GitHubContentsExecutionAdapter(
            token=TOKEN,
            repository="https://attacker.example/repo",
        )
