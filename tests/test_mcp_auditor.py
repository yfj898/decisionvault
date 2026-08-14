from __future__ import annotations

import pytest

from decisionvault.adaptive_memory import ADAPTIVE_MEMORY_GOVERNANCE_REVISION
from decisionvault.mcp_auditor import (
    ManagedMcpClient,
    MemoryAuditorAgent,
    _decode_mcp_body,
    _vector_literal,
)
from decisionvault.memory.governed_query import (
    adaptive_semantic_coverage_sql,
    semantic_coverage_sql,
)


def test_empty_notification_response_is_valid():
    assert _decode_mcp_body(b"", "application/json") == {}


def test_mcp_1024d_plan_queries_stay_below_managed_query_limit():
    vector = [(-1.0 if index % 2 else 1.0) * 0.123456789 for index in range(1024)]
    literal = _vector_literal(vector)
    vector_expr = f"'{literal}'::VECTOR"
    episode_coverage = semantic_coverage_sql(
        vector_expr=vector_expr,
        scope_expr="'scope'",
        space_expr="'space'",
        max_distance_expr="0.6",
    )
    adaptive_coverage = adaptive_semantic_coverage_sql(
        vector_expr=vector_expr,
        scope_expr="'scope'",
        space_expr="'space'",
        governance_revision_expr=f"'{ADAPTIVE_MEMORY_GOVERNANCE_REVISION}'",
        max_distance_expr="0.6",
    )
    assert len(episode_coverage) < 16_384
    assert len(adaptive_coverage) < 16_384


def test_managed_mcp_bearer_endpoint_is_fixed():
    with pytest.raises(ValueError, match="endpoint is fixed"):
        ManagedMcpClient(
            cluster_id="cluster",
            bearer_token="placeholder-token",
            endpoint="https://attacker.example/mcp",
        )


class FakeMcpClient:
    def __init__(self, *, semantic=False, adaptive=False):
        self.semantic = semantic
        self.adaptive = adaptive
        self.calls = []

    def initialize(self):
        return {
            "result": {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "cockroachdb-cloud"},
            }
        }

    def list_tools(self):
        return {
            "result": {
                "tools": [
                    {"name": "select_query"},
                    {"name": "explain_query"},
                ]
            }
        }

    def call_tool(self, name, arguments):
        self.calls.append((name, arguments["query"]))
        assert arguments["database"] == "defaultdb"
        if name == "select_query":
            if "decision_governed_memories" in arguments["query"]:
                assert self.adaptive is True
                return {
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "scope=shared-team producer_set=[recovery-observer-a,"
                                    "recovery-observer-b] supporting_episode_ids=[a,b]"
                                ),
                            }
                        ]
                    }
                }
            expected_table = (
                "decision_memory_heads" if self.semantic else "decision_episodes"
            )
            assert expected_table in arguments["query"]
            return {
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "scope=shared-team producer_agent_id="
                                "recovery-observer strategy=GENERIC_RETRY"
                            ),
                        }
                    ]
                }
            }
        if name == "explain_query":
            if "decision_governed_memories" in arguments["query"]:
                assert self.adaptive is True
                if "decision_governed_memory_support" in arguments["query"]:
                    return {
                        "result": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": (
                                        "scan decision_governed_memories filter "
                                        "decision_governed_memory_support "
                                        "decision_memory_heads"
                                    ),
                                }
                            ]
                        }
                    }
                return {
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "vector search "
                                    "decision_governed_memories_scope_space_semantic_vec_idx"
                                ),
                            }
                        ]
                    }
                }
            if self.semantic and "NOT EXISTS" in arguments["query"]:
                return {
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": "scan decision_memory_heads filter",
                            }
                        ]
                    }
                }
            expected = (
                "decision_memory_heads_scope_space_semantic_vec_idx"
                if self.semantic
                else "decision_episodes_scope_embedding_vec_idx"
            )
            return {
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "vector search " + expected
                            ),
                        }
                    ]
                }
            }
        raise AssertionError(name)


def test_memory_auditor_agent_checks_live_memory_contract():
    result = MemoryAuditorAgent(FakeMcpClient()).audit_scope(
        scope_id="shared-team",
        situation="payment failed after card replacement; token stale",
    )
    assert result.passed is True


def test_memory_auditor_agent_checks_production_semantic_contract():
    client = FakeMcpClient(semantic=True)
    result = MemoryAuditorAgent(client).audit_scope(
        scope_id="shared-team",
        situation="replacement card checkout failure",
        semantic_query_vector=[0.1, 0.9],
        semantic_embedding_space="test-space-v1",
    )
    assert result.passed is True
    explain_queries = [query for name, query in client.calls if name == "explain_query"]
    assert len(explain_queries) == 2
    assert "LIMIT 32" in explain_queries[0]
    assert "memory_status" not in explain_queries[0]
    assert "decision_memory_revocations" not in explain_queries[0]
    assert "decision_memory_revocations" in explain_queries[1]
    assert "memory_status" in explain_queries[1]


def test_memory_auditor_agent_checks_adaptive_memory_dvi_and_lineage_contract():
    client = FakeMcpClient(semantic=True, adaptive=True)
    result = MemoryAuditorAgent(client).audit_scope(
        scope_id="shared-team",
        situation="replacement card checkout failure",
        semantic_query_vector=[0.1, 0.9],
        semantic_embedding_space="test-space-v1",
        adaptive=True,
    )
    assert result.passed is True
    assert result.adaptive_memory_visible is True
    assert result.adaptive_provenance_visible is True
    assert result.adaptive_vector_plan_visible is True
    assert result.adaptive_vector_index_visible is True
    assert result.adaptive_coverage_plan_visible is True
    explain_queries = [query for name, query in client.calls if name == "explain_query"]
    adaptive_queries = [
        query for query in explain_queries if "decision_governed_memories" in query
    ]
    assert len(adaptive_queries) == 2
    assert "LIMIT 32" in adaptive_queries[0]
    assert "decision_governed_memory_support" not in adaptive_queries[0]
    assert "decision_governed_memory_support" in adaptive_queries[1]
    assert "decision_memory_heads" in adaptive_queries[1]
