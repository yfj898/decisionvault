from __future__ import annotations

import argparse
import os
from pathlib import Path
from uuid import uuid4

from decisionvault.agent.engine import DecisionAgent
from decisionvault.domain import Outcome, Strategy
from decisionvault.memory.cockroach import CockroachVectorMemoryStore
from decisionvault.memory.connection import psycopg_connection_factory
from decisionvault.memory.embedding import deterministic_text_embedding
from decisionvault.memory.inmemory import InMemoryEpisodeStore
from decisionvault.providers.bedrock import BedrockDecisionAdvisor, BedrockTextProvider
from decisionvault.providers.nvidia import NvidiaDecisionAdvisor


FIRST_CASE = (
    "customer payment failed twice after replacing their card "
    "and the stored payment token may be stale"
)
SIMILAR_CASE = (
    "payment failed again after the customer replaced the card; "
    "the saved token looks stale"
)


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_bedrock_env(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    values = load_env_file(path)
    token = values.get("AWS_BEARER_TOKEN_BEDROCK", "")
    if token and not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = token


def make_seeded_store(store, scope_id: str):
    agent = DecisionAgent(memory=store)
    decision = agent.decide(scope_id=scope_id, situation=FIRST_CASE)
    agent.record_outcome(
        scope_id=scope_id,
        situation=FIRST_CASE,
        decision=decision,
        outcome=Outcome.FAILED,
        effectiveness=0.1,
    )
    return store


def delete_scope(connection_factory, scope_id: str) -> None:
    conn = connection_factory()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM decision_episodes WHERE scope_id = %s",
                (scope_id,),
            )
        conn.commit()
    finally:
        conn.close()


def run_advisor(advisor, *, cloud_memory: bool) -> None:
    scope_id = f"phase5-model-smoke-{uuid4()}"
    connection_factory = None
    if cloud_memory:
        connection_factory = psycopg_connection_factory()
        store = CockroachVectorMemoryStore(
            connection_factory=connection_factory,
            embedder=deterministic_text_embedding,
        )
        delete_scope(connection_factory, scope_id)
        memory_source = "cockroachdb-cloud"
    else:
        store = InMemoryEpisodeStore()
        memory_source = "in-memory-test-store"

    make_seeded_store(store, scope_id)
    decision = DecisionAgent(memory=store, advisor=advisor).decide(
        scope_id=scope_id,
        situation=SIMILAR_CASE,
    )
    print(f"memory_source={memory_source}")
    print(f"strategy={decision.strategy.value}")
    print(f"memory_influenced={decision.memory_influenced}")
    print(f"model_provider={decision.model_provider}")
    print(f"model_explanation_present={bool(decision.model_explanation)}")
    if decision.model_explanation:
        print(f"model_explanation_chars={len(decision.model_explanation)}")

    if decision.strategy != Strategy.REFRESH_PAYMENT_TOKEN:
        raise RuntimeError("model integration changed the deterministic strategy")
    if not decision.memory_influenced:
        raise RuntimeError("memory influence evidence is missing")
    if not decision.model_explanation:
        raise RuntimeError("provider returned no explanation")
    print("bounded_model_advisor_smoke=PASS")

    if connection_factory is not None:
        delete_scope(connection_factory, scope_id)
        print("cloud_smoke_rows_cleaned=PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=("bedrock", "nvidia"))
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--nvidia-model", default="meta/llama-3.1-8b-instruct")
    parser.add_argument("--bedrock-model", default="amazon.nova-lite-v1:0")
    parser.add_argument("--bedrock-region", default="ap-northeast-1")
    parser.add_argument("--cloud-memory", action="store_true")
    args = parser.parse_args()

    if args.provider == "bedrock":
        load_bedrock_env(args.env_file)
        has_bedrock_api_key = bool(os.getenv("AWS_BEARER_TOKEN_BEDROCK"))
        has_aws_access_key = bool(
            os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")
        )
        has_aws_profile = bool(os.getenv("AWS_PROFILE"))
        if not (has_bedrock_api_key or has_aws_access_key or has_aws_profile):
            raise SystemExit(
                "Bedrock credentials are required. Set AWS_BEARER_TOKEN_BEDROCK "
                "or provide a standard AWS SDK credential source."
            )
        advisor = BedrockDecisionAdvisor(
            BedrockTextProvider(
                model_id=args.bedrock_model,
                region_name=args.bedrock_region,
            )
        )
    else:
        if args.env_file is None:
            raise SystemExit("--env-file is required for nvidia smoke")
        values = load_env_file(args.env_file)
        api_key = values.get("GUARDIAN_LLM_API_KEY", "")
        if not api_key:
            raise SystemExit("GUARDIAN_LLM_API_KEY missing from env file")
        advisor = NvidiaDecisionAdvisor(
            api_key=api_key,
            base_url=values.get(
                "GUARDIAN_LLM_BASE_URL",
                "https://integrate.api.nvidia.com/v1",
            ),
            model_id=args.nvidia_model,
        )

    run_advisor(advisor, cloud_memory=args.cloud_memory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
