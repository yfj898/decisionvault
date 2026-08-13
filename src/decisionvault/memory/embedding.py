from __future__ import annotations

from hashlib import sha256
from math import sqrt
import re


DEFAULT_EMBEDDING_DIMENSIONS = 64


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
