from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from decisionvault.benchmark import (
    benchmark_payload,
    build_benchmark_cases,
    run_benchmark,
    summarize_results,
)
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import deterministic_text_embedding
from decisionvault.memory.inmemory import InMemoryEpisodeStore
from decisionvault.providers.nvidia import NvidiaDecisionAdvisor


ROOT = Path(__file__).resolve().parents[1]


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def cleanup_cloud_prefix(connection_factory, scope_prefix: str) -> int:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM decision_episodes WHERE scope_id LIKE %s",
                (f"{scope_prefix}%",),
            )
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM decision_episodes WHERE scope_id LIKE %s",
                (f"{scope_prefix}%",),
            )
            return int(cur.fetchone()[0])
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("local", "cloud"), default="local")
    parser.add_argument("--variants", type=int, default=8)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--advisor", choices=("none", "nvidia"), default="none")
    parser.add_argument("--nvidia-env-file", type=Path)
    parser.add_argument("--nvidia-model", default="meta/llama-3.1-8b-instruct")
    args = parser.parse_args()

    run_id = uuid4().hex[:10]
    scope_prefix = f"phase8-{args.backend}-{run_id}"
    cases = build_benchmark_cases(variants=args.variants, scope_prefix=scope_prefix)

    connection_factory = None
    if args.backend == "cloud":
        if not os.getenv("DATABASE_URL"):
            raise SystemExit("DATABASE_URL is required for --backend cloud")
        connection_factory = psycopg_connection_factory()
        cleanup_cloud_prefix(connection_factory, scope_prefix)
        store = CockroachVectorMemoryStore(
            connection_factory=connection_factory,
            embedder=deterministic_text_embedding,
        )
    else:
        store = InMemoryEpisodeStore()

    advisor = None
    if args.advisor == "nvidia":
        if args.nvidia_env_file is None:
            raise SystemExit("--nvidia-env-file is required for --advisor nvidia")
        values = load_env_file(args.nvidia_env_file)
        api_key = values.get("GUARDIAN_LLM_API_KEY", "")
        if not api_key:
            raise SystemExit("GUARDIAN_LLM_API_KEY missing from NVIDIA env file")
        advisor = NvidiaDecisionAdvisor(
            api_key=api_key,
            base_url=values.get(
                "GUARDIAN_LLM_BASE_URL",
                "https://integrate.api.nvidia.com/v1",
            ),
            model_id=args.nvidia_model,
            timeout_seconds=20,
        )

    try:
        results = run_benchmark(store=store, cases=cases, advisor=advisor)
        summary = summarize_results(results)
        payload = benchmark_payload(
            backend=args.backend,
            variants=args.variants,
            results=results,
        )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        print(f"backend={args.backend}")
        print(f"total_cases={summary.total_cases}")
        print(f"passed_cases={summary.passed_cases}")
        print(f"overall_accuracy_on={summary.overall_accuracy_on:.4f}")
        print(f"overall_accuracy_off={summary.overall_accuracy_off:.4f}")
        print(
            f"benefit_target_accuracy_on={summary.benefit_target_accuracy_on:.4f}"
        )
        print(
            f"benefit_target_accuracy_off={summary.benefit_target_accuracy_off:.4f}"
        )
        print(
            f"control_preservation_rate_on={summary.control_preservation_rate_on:.4f}"
        )
        print(
            f"failed_retry_repetition_rate_on={summary.failed_retry_repetition_rate_on:.4f}"
        )
        print(
            f"failed_retry_repetition_rate_off={summary.failed_retry_repetition_rate_off:.4f}"
        )
        print(
            f"successful_strategy_reuse_rate_on={summary.successful_strategy_reuse_rate_on:.4f}"
        )
        print(
            f"successful_strategy_reuse_rate_off={summary.successful_strategy_reuse_rate_off:.4f}"
        )
        print(
            f"cross_scope_leakage_rate_on={summary.cross_scope_leakage_rate_on:.4f}"
        )
        print(f"false_influence_rate_on={summary.false_influence_rate_on:.4f}")
        if summary.advisor_strategy_invariance_rate is not None:
            print(
                "advisor_strategy_invariance_rate="
                f"{summary.advisor_strategy_invariance_rate:.4f}"
            )
        print(
            "phase8_benchmark="
            + ("PASS" if summary.passed_cases == summary.total_cases else "FAIL")
        )
        return 0 if summary.passed_cases == summary.total_cases else 1
    finally:
        if connection_factory is not None:
            remaining = cleanup_cloud_prefix(connection_factory, scope_prefix)
            print(f"cloud_rows_after_cleanup={remaining}")


if __name__ == "__main__":
    raise SystemExit(main())
