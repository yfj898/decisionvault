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
