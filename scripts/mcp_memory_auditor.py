from __future__ import annotations

import argparse
import os

from decisionvault.mcp_auditor import ManagedMcpClient, MemoryAuditorAgent
from decisionvault.memory.embedding import NvidiaSemanticEmbedder


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--situation", required=True)
    parser.add_argument("--database", default="defaultdb")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--adaptive", action="store_true")
    args = parser.parse_args()

    cluster_id = os.getenv("COCKROACH_CLUSTER_ID", "").strip()
    token = (
        os.getenv("COCKROACH_MCP_BEARER_TOKEN", "").strip()
        or os.getenv("COCKROACH_MCP_API_KEY", "").strip()
    )
    if not cluster_id or not token:
        raise SystemExit(
            "COCKROACH_CLUSTER_ID and COCKROACH_MCP_BEARER_TOKEN/"
            "COCKROACH_MCP_API_KEY are required"
        )

    semantic_query_vector = None
    semantic_embedding_space = None
    if args.semantic or args.adaptive:
        nvidia_key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not nvidia_key:
            raise SystemExit("NVIDIA_API_KEY is required for --semantic")
        semantic = NvidiaSemanticEmbedder(
            api_key=nvidia_key,
            revision=os.getenv("NVIDIA_EMBED_REVISION", "").strip(),
            model_id=os.getenv(
                "NVIDIA_EMBED_MODEL_ID", "nvidia/nv-embedqa-e5-v5"
            ),
            base_url=os.getenv(
                "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
            ),
        )
        semantic_query_vector = semantic.embed_query(args.situation)
        semantic_embedding_space = semantic.embedding_space

    result = MemoryAuditorAgent(
        ManagedMcpClient(cluster_id=cluster_id, bearer_token=token),
        database=args.database,
    ).audit_scope(
        scope_id=args.scope_id,
        situation=args.situation,
        semantic_query_vector=semantic_query_vector,
        semantic_embedding_space=semantic_embedding_space,
        adaptive=args.adaptive,
    )
    print(f"server_initialized={result.server_initialized}")
    print(f"required_tools_present={result.required_tools_present}")
    print(f"scope_memory_visible={result.scope_memory_visible}")
    print(f"producer_provenance_visible={result.producer_provenance_visible}")
    print(f"vector_plan_visible={result.vector_plan_visible}")
    print(f"vector_index_visible={result.vector_index_visible}")
    print(f"adaptive_memory_visible={result.adaptive_memory_visible}")
    print(f"adaptive_provenance_visible={result.adaptive_provenance_visible}")
    print(f"adaptive_vector_plan_visible={result.adaptive_vector_plan_visible}")
    print(f"adaptive_vector_index_visible={result.adaptive_vector_index_visible}")
    print(f"adaptive_coverage_plan_visible={result.adaptive_coverage_plan_visible}")
    print(f"memory_auditor_agent={'PASS' if result.passed else 'FAIL'}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
