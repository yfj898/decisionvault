from __future__ import annotations

from functools import lru_cache
import json
import os


SECRET_KEYS = frozenset(
    {
        "DATABASE_URL",
        "NVIDIA_API_KEY",
        "DEMO_API_TOKEN",
        "AGENT_AUTH_JSON",
        "EXECUTION_RECEIPT_SECRET",
    }
)


@lru_cache(maxsize=1)
def load_runtime_secrets() -> dict[str, str]:
    """Load the single DecisionVault runtime secret once per warm process.

    Local development may continue to supply the individual values directly in
    the process environment. The hosted Lambda supplies only
    ``DECISIONVAULT_SECRET_ARN`` and resolves the sensitive values from AWS
    Secrets Manager at runtime.
    """

    secret_arn = os.getenv("DECISIONVAULT_SECRET_ARN", "").strip()
    if not secret_arn:
        return {}

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
    return values


def hydrate_runtime_secrets() -> None:
    """Populate only missing sensitive process values from Secrets Manager."""

    for key, value in load_runtime_secrets().items():
        os.environ.setdefault(key, value)
