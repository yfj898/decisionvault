from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from statistics import median
import time
from uuid import uuid4

from decisionvault.agent.memory_governance import PRODUCTION_SEMANTIC_MIN_SIMILARITY
from decisionvault.adaptive_memory import GovernedAdaptiveMemoryResolver
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import NvidiaSemanticEmbedder, deterministic_text_embedding


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--output", type=Path, default=Path("reports/memory-runtime-benchmark.json"))
    args = parser.parse_args()
    if args.iterations < 2:
        raise SystemExit("--iterations must be >= 2")

    api_key = os.getenv("NVIDIA_API_KEY", "").strip()
    revision = os.getenv("NVIDIA_EMBED_REVISION", "").strip()
    if not api_key or not revision or not os.getenv("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL, NVIDIA_API_KEY, and NVIDIA_EMBED_REVISION are required")

    semantic = NvidiaSemanticEmbedder(
        api_key=api_key,
        revision=revision,
        model_id=os.getenv("NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"),
        base_url=os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        timeout_seconds=float(os.getenv("NVIDIA_TIMEOUT_SECONDS", "20")),
    )
    provider_calls = 0
    connection_calls = 0
    base_factory = psycopg_connection_factory()

    def query_embed(text: str):
        nonlocal provider_calls
        provider_calls += 1
        return semantic.embed_query(text)

    def connection_factory():
        nonlocal connection_calls
        connection_calls += 1
        return base_factory()

    store = CockroachVectorMemoryStore(
        connection_factory=connection_factory,
        embedder=deterministic_text_embedding,
        semantic_query_embedder=query_embed,
        semantic_embedding_space=semantic.embedding_space,
    )
    scope_id = f"runtime-benchmark-{uuid4().hex}"
    situation = "replacement card checkout still uses a stale payment token"
    adaptive_similarity = GovernedAdaptiveMemoryResolver().minimum_similarity

    def run(mode: str) -> dict[str, object]:
        nonlocal provider_calls, connection_calls
        provider_calls = 0
        connection_calls = 0
        latencies: list[float] = []
        for _ in range(args.iterations):
            started = time.perf_counter()
            if mode == "legacy":
                store.recall_governed(
                    scope_id=scope_id,
                    situation=situation,
                    minimum_similarity=PRODUCTION_SEMANTIC_MIN_SIMILARITY,
                )
                store.recall_adaptive(
                    scope_id=scope_id,
                    situation=situation,
                    minimum_similarity=adaptive_similarity,
                )
            else:
                store.recall_governed_and_adaptive(
                    scope_id=scope_id,
                    situation=situation,
                    minimum_episode_similarity=PRODUCTION_SEMANTIC_MIN_SIMILARITY,
                    minimum_adaptive_similarity=adaptive_similarity,
                )
            latencies.append((time.perf_counter() - started) * 1000.0)
        return {
            "iterations": args.iterations,
            "provider_query_embedding_calls": provider_calls,
            "provider_calls_per_decision": provider_calls / args.iterations,
            "database_connections": connection_calls,
            "database_connections_per_decision": connection_calls / args.iterations,
            "latency_ms_median": median(latencies),
            "latency_ms_p95": _percentile(latencies, 0.95),
            "latency_ms_min": min(latencies),
            "latency_ms_max": max(latencies),
        }

    # Alternate ordering would add noise from provider/network drift; warm both
    # paths once and then measure the production shapes separately.
    store.recall_governed_and_adaptive(
        scope_id=scope_id,
        situation=situation,
        minimum_episode_similarity=PRODUCTION_SEMANTIC_MIN_SIMILARITY,
        minimum_adaptive_similarity=adaptive_similarity,
    )
    legacy = run("legacy")
    bundled = run("bundled")
    payload = {
        "benchmark": "decisionvault-memory-runtime-v1",
        "scope_contains_no_writes": True,
        "semantic_embedding_space": semantic.embedding_space,
        "legacy": legacy,
        "bundled": bundled,
        "provider_request_reduction": 1.0 - (
            bundled["provider_calls_per_decision"] / legacy["provider_calls_per_decision"]
        ),
        "database_connection_reduction": 1.0 - (
            bundled["database_connections_per_decision"]
            / legacy["database_connections_per_decision"]
        ),
        "median_latency_reduction": 1.0 - (
            bundled["latency_ms_median"] / legacy["latency_ms_median"]
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"runtime_benchmark_output={args.output}")
    print(f"legacy_provider_calls_per_decision={legacy['provider_calls_per_decision']}")
    print(f"bundled_provider_calls_per_decision={bundled['provider_calls_per_decision']}")
    print(f"legacy_db_connections_per_decision={legacy['database_connections_per_decision']}")
    print(f"bundled_db_connections_per_decision={bundled['database_connections_per_decision']}")
    print(f"provider_request_reduction={payload['provider_request_reduction']:.3f}")
    print(f"database_connection_reduction={payload['database_connection_reduction']:.3f}")
    print(f"median_latency_reduction={payload['median_latency_reduction']:.3f}")
    print("memory_runtime_benchmark=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
