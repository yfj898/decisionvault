from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.request import Request, urlopen

from decisionvault.memory.embedding import deterministic_text_embedding


MCP_PROTOCOL_VERSION = "2025-06-18"


def _vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in values) + "]"


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
    endpoint: str = "https://cockroachlabs.cloud/mcp"
    timeout_seconds: float = 30.0
    session_id: str | None = None
    _request_id: int = 0

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
        with urlopen(request, timeout=self.timeout_seconds) as response:
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
        select_payload = self.client.call_tool(
            "select_query",
            {
                "database": self.database,
                "query": (
                    "SELECT scope_id, strategy, outcome, effectiveness, confidence, "
                    "evidence->>'producer_agent_id' AS producer_agent_id "
                    f"FROM {'decision_memory_heads' if semantic_mode else 'decision_episodes'} "
                    f"WHERE scope_id = {scope_literal} ORDER BY created_at DESC LIMIT 5"
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
            "decision_memory_heads_scope_semantic_vec_idx"
            if semantic_mode
            else "decision_episodes_scope_embedding_vec_idx"
        )
        explain_payload = self.client.call_tool(
            "explain_query",
            {
                "database": self.database,
                "query": (
                    f"SELECT episode_id FROM {table} "
                    f"WHERE scope_id = {scope_literal} "
                    f"ORDER BY {column} <=> '{vector}'::VECTOR LIMIT 5"
                ),
            },
        )
        explain_text = _response_text(explain_payload).lower()
        vector_plan_visible = "vector search" in explain_text
        vector_index_visible = index_name in explain_text
        return MemoryAuditResult(
            server_initialized=server_initialized,
            required_tools_present=required_tools_present,
            scope_memory_visible=scope_memory_visible,
            producer_provenance_visible=producer_provenance_visible,
            vector_plan_visible=vector_plan_visible,
            vector_index_visible=vector_index_visible,
        )
