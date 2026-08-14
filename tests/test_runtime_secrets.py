from __future__ import annotations

import json

import decisionvault.runtime_secrets as runtime_secrets


class FakeSecretsClient:
    def __init__(self, payload):
        self.payload = payload

    def get_secret_value(self, *, SecretId):
        assert SecretId == "arn:test:decisionvault"
        return {"SecretString": json.dumps(self.payload)}


class FakeBoto3:
    def __init__(self, payload):
        self.payload = payload

    def client(self, name):
        assert name == "secretsmanager"
        return FakeSecretsClient(self.payload)


def _payload():
    return {
        "DATABASE_URL": "postgresql://runtime",
        "NVIDIA_API_KEY": "nvidia-key",
        "DEMO_API_TOKEN": "demo-token",
        "AGENT_AUTH_JSON": "{}",
        "EXECUTION_RECEIPT_SECRET": "receipt-secret-value",
    }


def test_no_secret_arn_keeps_local_environment_mode(monkeypatch):
    runtime_secrets.load_runtime_secrets.cache_clear()
    monkeypatch.delenv("DECISIONVAULT_SECRET_ARN", raising=False)
    assert runtime_secrets.load_runtime_secrets() == {}


def test_secrets_manager_payload_hydrates_only_missing_values(monkeypatch):
    import sys

    runtime_secrets.load_runtime_secrets.cache_clear()
    monkeypatch.setenv("DECISIONVAULT_SECRET_ARN", "arn:test:decisionvault")
    monkeypatch.setenv("DEMO_API_TOKEN", "local-override")
    for key in runtime_secrets.SECRET_KEYS - {"DEMO_API_TOKEN"}:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(sys.modules, "boto3", FakeBoto3(_payload()))

    runtime_secrets.hydrate_runtime_secrets()

    assert __import__("os").environ["DATABASE_URL"] == "postgresql://runtime"
    assert __import__("os").environ["NVIDIA_API_KEY"] == "nvidia-key"
    assert __import__("os").environ["DEMO_API_TOKEN"] == "local-override"


def test_runtime_secret_requires_all_sensitive_keys(monkeypatch):
    import sys
    import pytest

    runtime_secrets.load_runtime_secrets.cache_clear()
    monkeypatch.setenv("DECISIONVAULT_SECRET_ARN", "arn:test:decisionvault")
    payload = _payload()
    payload.pop("DATABASE_URL")
    monkeypatch.setitem(sys.modules, "boto3", FakeBoto3(payload))
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        runtime_secrets.load_runtime_secrets()
