from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.request import Request

from decisionvault.adaptive_memory import ADAPTIVE_MEMORY_GOVERNANCE_REVISION
from decisionvault.agent.memory_governance import PRODUCTION_SEMANTIC_MIN_SIMILARITY
from decisionvault.memory.embedding import deterministic_text_embedding
from decisionvault.memory.governed_query import (
    adaptive_semantic_ann_sql,
    adaptive_semantic_coverage_sql,
    semantic_ann_sql,
    semantic_coverage_sql,
)
from decisionvault.providers.http_security import open_fixed_bearer_request


MCP_PROTOCOL_VERSION = "2025-06-18"
MANAGED_MCP_ENDPOINT = "https://cockroachlabs.cloud/mcp"


def _vector_literal(values: list[float]) -> str:
    # Managed MCP rejects tool queries longer than 16,384 characters. A native
    # 1024D embedding can exceed that limit because the production ANN/coverage
    # SQL references the same vector expression more than once. MCP uses this
    # literal only for EXPLAIN, never for retrieval or a DecisionVault decision,
    # so preserve dimensionality/non-zero direction while quantizing each
    # component to its sign. This keeps the *production SQL builders and index
    # predicates* identical while making the plan-only request size bounded.
    compact = []
    for value in values:
        numeric = float(value)
        compact.append("1" if numeric > 0 else "-1" if numeric < 0 else "0")
    return "[" + ",".join(compact) + "]"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _decode_mcp_body(raw: bytes, content_type: str) -> dict[str, Any]:
    text = raw.decode("utf-8")
    if not text.strip():
        return {}
    if "text/event-stream" not in content_type:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise RuntimeError("MCP response is not a JSON object")
        return payload

    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        payload = json.loads(line[5:].strip())
        if isinstance(payload, dict):
            return payload
    raise RuntimeError("MCP SSE response did not contain a JSON data event")


@dataclass(slots=True)
class ManagedMcpClient:
    cluster_id: str
    bearer_token: str
    endpoint: str = MANAGED_MCP_ENDPOINT
    timeout_seconds: float = 30.0
    session_id: str | None = None
    _request_id: int = 0

    def __post_init__(self) -> None:
        if self.endpoint.strip().rstrip("/") != MANAGED_MCP_ENDPOINT:
            raise ValueError("Managed MCP endpoint is fixed by DecisionVault")
        self.endpoint = MANAGED_MCP_ENDPOINT

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.bearer_token}",
            "mcp-cluster-id": self.cluster_id,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
            headers["MCP-Protocol-Version"] = MCP_PROTOCOL_VERSION
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with open_fixed_bearer_request(
            request,
            allowed_url=MANAGED_MCP_ENDPOINT,
            timeout_seconds=self.timeout_seconds,
        ) as response:
            if not self.session_id:
                self.session_id = response.headers.get("mcp-session-id")
            return _decode_mcp_body(
                response.read(),
                response.headers.get("content-type", ""),
            )

    def initialize(self) -> dict[str, Any]:
        response = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "initialize",
                "params": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": "decisionvault-memory-auditor",
                        "version": "0.1.0",
                    },
                },
            }
        )
        self._post(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            }
        )
        return response

    def list_tools(self) -> dict[str, Any]:
        return self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/list",
                "params": {},
            }
        )

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id(),
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            }
        )


def _response_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload.get("result", payload), sort_keys=True)


@dataclass(frozen=True, slots=True)
class MemoryAuditResult:
    server_initialized: bool
    required_tools_present: bool
    scope_memory_visible: bool
    producer_provenance_visible: bool
    vector_plan_visible: bool
    vector_index_visible: bool
    coverage_plan_visible: bool = True
    adaptive_memory_visible: bool = True
    adaptive_provenance_visible: bool = True
    adaptive_vector_plan_visible: bool = True
    adaptive_vector_index_visible: bool = True
    adaptive_coverage_plan_visible: bool = True

    @property
    def passed(self) -> bool:
        return all(
            (
                self.server_initialized,
                self.required_tools_present,
                self.scope_memory_visible,
                self.producer_provenance_visible,
                self.vector_plan_visible,
                self.vector_index_visible,
                self.coverage_plan_visible,
                self.adaptive_memory_visible,
                self.adaptive_provenance_visible,
                self.adaptive_vector_plan_visible,
                self.adaptive_vector_index_visible,
                self.adaptive_coverage_plan_visible,
            )
        )


@dataclass(slots=True)
class MemoryAuditorAgent:
    client: ManagedMcpClient
    database: str = "defaultdb"

    def audit_scope(
        self,
        *,
        scope_id: str,
        situation: str,
        semantic_query_vector: list[float] | None = None,
        semantic_embedding_space: str | None = None,
        adaptive: bool = False,
    ) -> MemoryAuditResult:
        init = self.client.initialize()
        init_text = _response_text(init)
        server_initialized = (
            MCP_PROTOCOL_VERSION in init_text and "cockroachdb-cloud" in init_text
        )

        tools_payload = self.client.list_tools()
        tools_text = _response_text(tools_payload)
        required_tools_present = all(
            tool in tools_text for tool in ("select_query", "explain_query")
        )

        scope_literal = _sql_literal(scope_id)
        semantic_mode = semantic_query_vector is not None
        if semantic_mode and not (semantic_embedding_space or "").strip():
            raise ValueError(
                "semantic_embedding_space is required for semantic MCP audit"
            )
        space_clause = (
            " AND semantic_embedding_space = "
            + _sql_literal(str(semantic_embedding_space))
            if semantic_mode
            else ""
        )
        select_payload = self.client.call_tool(
            "select_query",
            {
                "database": self.database,
                "query": (
                    "SELECT scope_id, strategy, outcome, effectiveness, confidence, "
                    "evidence->>'producer_agent_id' AS producer_agent_id "
                    f"FROM {'decision_memory_heads' if semantic_mode else 'decision_episodes'} "
                    f"WHERE scope_id = {scope_literal}{space_clause} "
                    "ORDER BY observed_at DESC LIMIT 5"
                ),
            },
        )
        select_text = _response_text(select_payload)
        scope_memory_visible = scope_id in select_text
        producer_provenance_visible = "producer_agent_id" in select_text

        vector = _vector_literal(
            semantic_query_vector
            if semantic_query_vector is not None
            else deterministic_text_embedding(situation)
        )
        table = "decision_memory_heads" if semantic_mode else "decision_episodes"
        column = "semantic_embedding" if semantic_mode else "embedding"
        index_name = (
            "decision_memory_heads_scope_space_semantic_vec_idx"
            if semantic_mode
            else "decision_episodes_scope_embedding_vec_idx"
        )
        if semantic_mode:
            vector_expr = f"'{vector}'::VECTOR"
            production_ann_query = semantic_ann_sql(
                vector_expr=vector_expr,
                scope_expr=scope_literal,
                space_expr=_sql_literal(str(semantic_embedding_space)),
            )
        else:
            production_ann_query = (
                f"SELECT episode_id FROM {table} "
                f"WHERE scope_id = {scope_literal}{space_clause} "
                f"ORDER BY {column} <=> '{vector}'::VECTOR LIMIT 5"
            )
        explain_payload = self.client.call_tool(
            "explain_query",
            {
                "database": self.database,
                "query": production_ann_query,
            },
        )
        explain_text = _response_text(explain_payload).lower()
        vector_plan_visible = "vector search" in explain_text
        vector_index_visible = index_name in explain_text
        coverage_plan_visible = True
        if semantic_mode:
            coverage_query = semantic_coverage_sql(
                vector_expr=f"'{vector}'::VECTOR",
                scope_expr=scope_literal,
                space_expr=_sql_literal(str(semantic_embedding_space)),
                max_distance_expr=str(1.0 - PRODUCTION_SEMANTIC_MIN_SIMILARITY),
            )
            coverage_payload = self.client.call_tool(
                "explain_query",
                {"database": self.database, "query": coverage_query},
            )
            coverage_text = _response_text(coverage_payload).lower()
            coverage_plan_visible = (
                "decision_memory_heads" in coverage_text
                and ("scan" in coverage_text or "filter" in coverage_text)
            )
        adaptive_memory_visible = True
        adaptive_provenance_visible = True
        adaptive_vector_plan_visible = True
        adaptive_vector_index_visible = True
        adaptive_coverage_plan_visible = True
        if adaptive:
            if not semantic_mode:
                raise ValueError("adaptive MCP audit requires semantic query vector")
            space_literal = _sql_literal(str(semantic_embedding_space))
            revision_literal = _sql_literal(ADAPTIVE_MEMORY_GOVERNANCE_REVISION)
            adaptive_select = self.client.call_tool(
                "select_query",
                {
                    "database": self.database,
                    "query": (
                        "SELECT memory_id, scope_id, memory_type, polarity, intervention, "
                        "producer_set, supporting_episode_ids, status "
                        "FROM decision_governed_memories "
                        f"WHERE scope_id = {scope_literal} "
                        f"AND semantic_embedding_space = {space_literal} "
                        f"AND governance_revision = {revision_literal} "
                        "ORDER BY observed_to DESC LIMIT 5"
                    ),
                },
            )
            adaptive_select_text = _response_text(adaptive_select)
            adaptive_memory_visible = scope_id in adaptive_select_text
            adaptive_provenance_visible = all(
                marker in adaptive_select_text
                for marker in ("producer_set", "supporting_episode_ids")
            )
            adaptive_ann = adaptive_semantic_ann_sql(
                vector_expr=f"'{vector}'::VECTOR",
                scope_expr=scope_literal,
                space_expr=space_literal,
            )
            adaptive_explain = self.client.call_tool(
                "explain_query",
                {"database": self.database, "query": adaptive_ann},
            )
            adaptive_explain_text = _response_text(adaptive_explain).lower()
            adaptive_vector_plan_visible = "vector search" in adaptive_explain_text
            adaptive_vector_index_visible = (
                "decision_governed_memories_scope_space_semantic_vec_idx"
                in adaptive_explain_text
            )
            adaptive_coverage = adaptive_semantic_coverage_sql(
                vector_expr=f"'{vector}'::VECTOR",
                scope_expr=scope_literal,
                space_expr=space_literal,
                governance_revision_expr=revision_literal,
                max_distance_expr=str(1.0 - PRODUCTION_SEMANTIC_MIN_SIMILARITY),
            )
            adaptive_coverage_payload = self.client.call_tool(
                "explain_query",
                {"database": self.database, "query": adaptive_coverage},
            )
            adaptive_coverage_text = _response_text(adaptive_coverage_payload).lower()
            adaptive_coverage_plan_visible = all(
                marker in adaptive_coverage_text
                for marker in (
                    "decision_governed_memories",
                    "decision_governed_memory_support",
                    "decision_memory_heads",
                )
            ) and ("scan" in adaptive_coverage_text or "filter" in adaptive_coverage_text)
        return MemoryAuditResult(
            server_initialized=server_initialized,
            required_tools_present=required_tools_present,
            scope_memory_visible=scope_memory_visible,
            producer_provenance_visible=producer_provenance_visible,
            vector_plan_visible=vector_plan_visible,
            vector_index_visible=vector_index_visible,
            coverage_plan_visible=coverage_plan_visible,
            adaptive_memory_visible=adaptive_memory_visible,
            adaptive_provenance_visible=adaptive_provenance_visible,
            adaptive_vector_plan_visible=adaptive_vector_plan_visible,
            adaptive_vector_index_visible=adaptive_vector_index_visible,
            adaptive_coverage_plan_visible=adaptive_coverage_plan_visible,
        )
