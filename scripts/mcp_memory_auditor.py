from __future__ import annotations

import argparse
import os

from decisionvault.mcp_auditor import ManagedMcpClient, MemoryAuditorAgent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope-id", required=True)
    parser.add_argument("--situation", required=True)
    parser.add_argument("--database", default="defaultdb")
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

    result = MemoryAuditorAgent(
        ManagedMcpClient(cluster_id=cluster_id, bearer_token=token),
        database=args.database,
    ).audit_scope(scope_id=args.scope_id, situation=args.situation)
    print(f"server_initialized={result.server_initialized}")
    print(f"required_tools_present={result.required_tools_present}")
    print(f"scope_memory_visible={result.scope_memory_visible}")
    print(f"producer_provenance_visible={result.producer_provenance_visible}")
    print(f"vector_plan_visible={result.vector_plan_visible}")
    print(f"vector_index_visible={result.vector_index_visible}")
    print(f"memory_auditor_agent={'PASS' if result.passed else 'FAIL'}")
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
