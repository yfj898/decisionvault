from __future__ import annotations

from urllib.request import Request

import pytest

from decisionvault.memory.embedding import NvidiaSemanticEmbedder
from decisionvault.providers.bedrock import BedrockTextProvider
from decisionvault.providers.http_security import (
    NVIDIA_API_BASE_URL,
    nvidia_endpoint,
    open_nvidia_request,
    validate_nvidia_base_url,
)
from decisionvault.providers.nvidia import NvidiaDecisionAdvisor


@pytest.mark.parametrize(
    "value",
    [
        "https://attacker.example/v1",
        "http://integrate.api.nvidia.com/v1",
        "https://integrate.api.nvidia.com:444/v1",
        "https://integrate.api.nvidia.com/v1/../evil",
        "https://integrate.api.nvidia.com/v1?next=https://attacker.example",
        "https://user@integrate.api.nvidia.com/v1",
    ],
)
def test_nvidia_base_url_rejects_noncanonical_credential_destinations(value):
    with pytest.raises(ValueError, match="fixed DecisionVault NVIDIA provider origin"):
        validate_nvidia_base_url(value)


def test_nvidia_base_url_accepts_only_canonical_origin_and_path():
    assert validate_nvidia_base_url(None) == NVIDIA_API_BASE_URL
    assert validate_nvidia_base_url(NVIDIA_API_BASE_URL + "/") == NVIDIA_API_BASE_URL
    assert nvidia_endpoint(NVIDIA_API_BASE_URL, "embeddings") == (
        NVIDIA_API_BASE_URL + "/embeddings"
    )


def test_nvidia_provider_constructors_fail_before_any_request_on_bad_origin():
    with pytest.raises(ValueError):
        NvidiaSemanticEmbedder(
            api_key="placeholder-key",
            revision="test-r1",
            base_url="https://attacker.example/v1",
        )
    with pytest.raises(ValueError):
        NvidiaDecisionAdvisor(
            api_key="placeholder-key",
            base_url="https://attacker.example/v1",
        )


def test_nvidia_request_helper_refuses_nonallowlisted_url_before_network():
    request = Request(
        "https://attacker.example/collect",
        headers={"Authorization": "Bearer placeholder-key"},
    )
    with pytest.raises(ValueError, match="credential forwarding"):
        open_nvidia_request(request, timeout_seconds=1.0)


def test_bedrock_bearer_hostname_inputs_are_bounded():
    with pytest.raises(ValueError, match="region"):
        BedrockTextProvider(
            model_id="amazon.nova-lite-v1:0",
            region_name="ap-northeast-1.attacker.example",
        )


def _fake_opener(responses):
    from urllib.error import HTTPError

    class FakeOpener:
        def __init__(self):
            self.calls = 0

        def open(self, request, timeout=None):
            self.calls += 1
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response

    return FakeOpener()


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _nvidia_ok_request() -> Request:
    return Request(
        NVIDIA_API_BASE_URL + "/embeddings",
        data=b"{}",
        headers={"Authorization": "Bearer placeholder-key"},
    )


def test_nvidia_retry_succeeds_after_single_5xx(
    monkeypatch,
):
    import time
    from urllib.error import HTTPError

    opener = _fake_opener(
        [HTTPError(NVIDIA_API_BASE_URL + "/embeddings", 503, "unavailable", None, None), _Response()]
    )
    monkeypatch.setattr(
        "decisionvault.providers.http_security.build_opener", lambda *_a, **_k: opener
    )
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    with open_nvidia_request(_nvidia_ok_request(), timeout_seconds=5.0) as resp:
        assert resp is not None
    assert opener.calls == 2


def test_nvidia_retry_succeeds_after_connection_reset(monkeypatch):
    from urllib.error import URLError

    opener = _fake_opener([URLError(ConnectionResetError("reset")), _Response()])
    monkeypatch.setattr(
        "decisionvault.providers.http_security.build_opener", lambda *_a, **_k: opener
    )
    with open_nvidia_request(_nvidia_ok_request(), timeout_seconds=5.0) as resp:
        assert resp is not None
    assert opener.calls == 2


def test_nvidia_does_not_retry_timeout(monkeypatch):
    from urllib.error import URLError

    opener = _fake_opener([URLError(TimeoutError("deadline"))])
    monkeypatch.setattr(
        "decisionvault.providers.http_security.build_opener", lambda *_a, **_k: opener
    )
    with pytest.raises(URLError):
        with open_nvidia_request(_nvidia_ok_request(), timeout_seconds=5.0):
            pass
    assert opener.calls == 1


def test_nvidia_does_not_retry_client_errors(monkeypatch):
    from urllib.error import HTTPError

    opener = _fake_opener(
        [HTTPError(NVIDIA_API_BASE_URL + "/embeddings", 401, "unauthorized", None, None)]
    )
    monkeypatch.setattr(
        "decisionvault.providers.http_security.build_opener", lambda *_a, **_k: opener
    )
    with pytest.raises(HTTPError):
        with open_nvidia_request(_nvidia_ok_request(), timeout_seconds=5.0):
            pass
    assert opener.calls == 1


def test_nvidia_retry_exhausts_and_reraises(monkeypatch):
    from urllib.error import HTTPError

    opener = _fake_opener(
        [
            HTTPError(NVIDIA_API_BASE_URL + "/embeddings", 502, "bad gateway", None, None),
            HTTPError(NVIDIA_API_BASE_URL + "/embeddings", 502, "bad gateway", None, None),
        ]
    )
    monkeypatch.setattr(
        "decisionvault.providers.http_security.build_opener", lambda *_a, **_k: opener
    )
    with pytest.raises(HTTPError):
        with open_nvidia_request(_nvidia_ok_request(), timeout_seconds=5.0):
            pass
    assert opener.calls == 2
