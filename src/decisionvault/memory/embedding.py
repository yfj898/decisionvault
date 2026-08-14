from __future__ import annotations

from hashlib import sha256
from math import sqrt
import re
from dataclasses import dataclass
import json
from urllib.request import Request

from decisionvault.providers.http_security import (
    NVIDIA_API_BASE_URL,
    nvidia_endpoint,
    open_nvidia_request,
    validate_nvidia_base_url,
)


DEFAULT_EMBEDDING_DIMENSIONS = 64
NVIDIA_EMBEDDING_DIMENSIONS = 1024
SEMANTIC_EMBEDDING_CONTRACT_VERSION = "query-passage-v1"


def semantic_embedding_space(
    model_id: str,
    *,
    revision: str,
    dimensions: int = NVIDIA_EMBEDDING_DIMENSIONS,
    contract_version: str = SEMANTIC_EMBEDDING_CONTRACT_VERSION,
) -> str:
    normalized_model = model_id.strip()
    if not normalized_model:
        raise ValueError("semantic embedding model_id is required")
    if dimensions <= 0:
        raise ValueError("semantic embedding dimensions must be positive")
    normalized_contract = contract_version.strip()
    if not normalized_contract:
        raise ValueError("semantic embedding contract version is required")
    normalized_revision = revision.strip()
    if not normalized_revision:
        raise ValueError("semantic embedding revision is required")
    return (
        f"{normalized_model}|revision={normalized_revision}|dim={dimensions}"
        f"|contract={normalized_contract}"
    )


def deterministic_text_embedding(
    text: str,
    *,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
) -> list[float]:
    """Return a stable, dependency-free hashing embedding for Phase 2 smoke tests.

    This is intentionally not presented as a model embedding. It exists so the
    CockroachDB persistence path can be verified before Bedrock is connected.
    Phase 5 will replace this embedder with a real provider while preserving the
    memory-store contract.
    """

    if dimensions <= 0:
        raise ValueError("dimensions must be positive")

    tokens = re.findall(r"[a-z0-9]+", text.lower())
    vector = [0.0] * dimensions
    for token in tokens:
        digest = sha256(token.encode("utf-8")).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign

    norm = sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def project_dense_embedding(
    values: list[float],
    *,
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS,
) -> list[float]:
    """Project a provider embedding into DecisionVault's frozen VECTOR(64).

    The projection is a deterministic signed feature hash. It preserves the
    existing CockroachDB schema and Distributed Vector Index while allowing the
    runtime to use a real semantic embedding provider.
    """
    if dimensions <= 0:
        raise ValueError("dimensions must be positive")
    projected = [0.0] * dimensions
    for index, raw_value in enumerate(values):
        digest = sha256(f"decisionvault-projection-v1:{index}".encode()).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        projected[bucket] += sign * float(raw_value)
    norm = sqrt(sum(value * value for value in projected))
    if norm == 0:
        return projected
    return [value / norm for value in projected]


@dataclass(slots=True)
class NvidiaSemanticEmbedder:
    api_key: str
    revision: str
    base_url: str = NVIDIA_API_BASE_URL
    model_id: str = "nvidia/nv-embedqa-e5-v5"
    timeout_seconds: float = 20.0
    expected_dimensions: int = NVIDIA_EMBEDDING_DIMENSIONS

    def __post_init__(self) -> None:
        self.base_url = validate_nvidia_base_url(self.base_url)
        if not self.revision.strip():
            raise ValueError("semantic embedding revision is required")

    @property
    def embedding_space(self) -> str:
        return semantic_embedding_space(
            self.model_id,
            revision=self.revision,
            dimensions=self.expected_dimensions,
        )

    def _embed(self, text: str, *, input_type: str) -> list[float]:
        body = json.dumps(
            {
                "input": [text],
                "model": self.model_id,
                "input_type": input_type,
                "modality": "text",
            }
        ).encode("utf-8")
        request = Request(
            nvidia_endpoint(self.base_url, "embeddings"),
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        with open_nvidia_request(
            request, timeout_seconds=self.timeout_seconds
        ) as response:
            payload = json.loads(response.read())
        dense = [float(value) for value in payload["data"][0]["embedding"]]
        if len(dense) != self.expected_dimensions:
            raise ValueError(
                "unexpected NVIDIA embedding width: "
                f"expected {self.expected_dimensions}, got {len(dense)}"
            )
        return dense

    def embed_passage(self, text: str) -> list[float]:
        return self._embed(text, input_type="passage")

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text, input_type="query")
