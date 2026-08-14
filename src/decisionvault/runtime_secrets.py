from __future__ import annotations

import json
import os
from threading import RLock
import time


SECRET_KEYS = frozenset(
    {
        "DATABASE_URL",
        "NVIDIA_API_KEY",
        "DEMO_API_TOKEN",
        "AGENT_AUTH_JSON",
        "EXECUTION_RECEIPT_SECRET",
    }
)


_SECRET_CACHE: dict[str, str] | None = None
_SECRET_CACHE_ARN: str | None = None
_SECRET_CACHE_AT = 0.0
_SECRET_LOCK = RLock()


def _secret_refresh_seconds() -> float:
    return max(1.0, float(os.getenv("SECRET_REFRESH_SECONDS", "30")))


def _clear_secret_cache() -> None:
    with _SECRET_LOCK:
        global _SECRET_CACHE, _SECRET_CACHE_ARN, _SECRET_CACHE_AT
        _SECRET_CACHE = None
        _SECRET_CACHE_ARN = None
        _SECRET_CACHE_AT = 0.0


def _load_runtime_secrets_locked(*, force: bool = False) -> dict[str, str]:
    """Load the runtime secret with a bounded warm-process refresh interval.

    Local development may continue to supply the individual values directly in
    the process environment. The hosted Lambda supplies only
    ``DECISIONVAULT_SECRET_ARN`` and resolves the sensitive values from AWS
    Secrets Manager at runtime.
    """

    secret_arn = os.getenv("DECISIONVAULT_SECRET_ARN", "").strip()
    if not secret_arn:
        return {}

    global _SECRET_CACHE, _SECRET_CACHE_ARN, _SECRET_CACHE_AT
    now = time.monotonic()
    if (
        not force
        and _SECRET_CACHE is not None
        and _SECRET_CACHE_ARN == secret_arn
        and now - _SECRET_CACHE_AT < _secret_refresh_seconds()
    ):
        return dict(_SECRET_CACHE)

    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - Lambda includes boto3
        raise RuntimeError("boto3 is required to load AWS runtime secrets") from exc

    response = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)
    raw = response.get("SecretString", "")
    if not raw:
        raise RuntimeError("DecisionVault runtime secret has no SecretString")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("DecisionVault runtime secret must be a JSON object")

    values: dict[str, str] = {}
    for key in SECRET_KEYS:
        value = payload.get(key)
        if value is not None:
            values[key] = str(value)
    missing = SECRET_KEYS - values.keys()
    if missing:
        raise RuntimeError(
            "DecisionVault runtime secret is missing required keys: "
            + ", ".join(sorted(missing))
        )
    _SECRET_CACHE = dict(values)
    _SECRET_CACHE_ARN = secret_arn
    _SECRET_CACHE_AT = now
    return values


def load_runtime_secrets(*, force: bool = False) -> dict[str, str]:
    """Load a complete secret generation under one warm-process lock."""

    with _SECRET_LOCK:
        return _load_runtime_secrets_locked(force=force)


def hydrate_runtime_secrets(*, force: bool = False) -> None:
    """Refresh one complete managed secret generation atomically in-process."""

    with _SECRET_LOCK:
        managed = bool(os.getenv("DECISIONVAULT_SECRET_ARN", "").strip())
        values = _load_runtime_secrets_locked(force=force)
        for key, value in values.items():
            if managed:
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)


# Preserve the old test/operator cache-reset seam while using a TTL cache.
load_runtime_secrets.cache_clear = _clear_secret_cache  # type: ignore[attr-defined]
