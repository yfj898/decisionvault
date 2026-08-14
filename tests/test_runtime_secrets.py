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


def test_secrets_manager_payload_is_authoritative_in_managed_mode(monkeypatch):
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
    assert __import__("os").environ["DEMO_API_TOKEN"] == "demo-token"


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


def test_runtime_secret_refresh_replaces_warm_process_credentials(monkeypatch):
    import os
    import sys

    holder = {"payload": _payload()}

    class DynamicClient:
        def get_secret_value(self, *, SecretId):
            assert SecretId == "arn:test:decisionvault"
            return {"SecretString": json.dumps(holder["payload"])}

    class DynamicBoto3:
        def client(self, name):
            assert name == "secretsmanager"
            return DynamicClient()

    runtime_secrets.load_runtime_secrets.cache_clear()
    monkeypatch.setenv("DECISIONVAULT_SECRET_ARN", "arn:test:decisionvault")
    monkeypatch.setenv("SECRET_REFRESH_SECONDS", "1")
    monkeypatch.setitem(sys.modules, "boto3", DynamicBoto3())
    ticks = iter([0.0, 2.0])
    monkeypatch.setattr(runtime_secrets.time, "monotonic", lambda: next(ticks))

    runtime_secrets.hydrate_runtime_secrets()
    holder["payload"] = {**_payload(), "DEMO_API_TOKEN": "rotated-demo-token"}
    runtime_secrets.hydrate_runtime_secrets()

    assert os.environ["DEMO_API_TOKEN"] == "rotated-demo-token"


def test_concurrent_secret_refresh_generations_are_serialized(monkeypatch):
    import sys
    import threading
    import time

    state = {"active": 0, "max_active": 0}
    state_lock = threading.Lock()

    class SlowClient:
        def get_secret_value(self, *, SecretId):
            assert SecretId == "arn:test:decisionvault"
            with state_lock:
                state["active"] += 1
                state["max_active"] = max(state["max_active"], state["active"])
            try:
                time.sleep(0.01)
                return {"SecretString": json.dumps(_payload())}
            finally:
                with state_lock:
                    state["active"] -= 1

    class SlowBoto3:
        def client(self, name):
            assert name == "secretsmanager"
            return SlowClient()

    runtime_secrets.load_runtime_secrets.cache_clear()
    monkeypatch.setenv("DECISIONVAULT_SECRET_ARN", "arn:test:decisionvault")
    monkeypatch.setitem(sys.modules, "boto3", SlowBoto3())
    threads = [
        threading.Thread(
            target=runtime_secrets.hydrate_runtime_secrets,
            kwargs={"force": True},
        )
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert state["max_active"] == 1
