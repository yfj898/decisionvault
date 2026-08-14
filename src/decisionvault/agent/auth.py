from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Mapping


SCOPE_BOUNDARIES = frozenset("-/:._")
AGENT_PERMISSIONS = frozenset({"decide", "execute", "record", "revoke"})


def _scope_prefix_matches(prefix: str, scope_id: str) -> bool:
    if scope_id == prefix:
        return True
    if not scope_id.startswith(prefix):
        return False
    if prefix[-1] in SCOPE_BOUNDARIES:
        return True
    return len(scope_id) > len(prefix) and scope_id[len(prefix)] in SCOPE_BOUNDARIES


@dataclass(frozen=True, slots=True)
class AgentGrant:
    agent_id: str
    scope_prefixes: tuple[str, ...]
    permissions: frozenset[str]
    trust: float = 0.25

    def allows(self, *, permission: str, scope_id: str) -> bool:
        if permission not in self.permissions:
            return False
        return any(_scope_prefix_matches(prefix, scope_id) for prefix in self.scope_prefixes)


def token_digest(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def load_agent_grants(raw: str) -> dict[str, AgentGrant]:
    if not raw.strip():
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("AGENT_AUTH_JSON must be a JSON object")

    grants: dict[str, AgentGrant] = {}
    agent_ids: set[str] = set()
    for digest, value in payload.items():
        if not isinstance(value, dict):
            raise ValueError("each AGENT_AUTH_JSON grant must be an object")
        digest_text = str(digest).lower().strip()
        if len(digest_text) != 64 or any(
            character not in "0123456789abcdef" for character in digest_text
        ):
            raise ValueError("AGENT_AUTH_JSON keys must be SHA-256 token digests")
        agent_id = str(value.get("agent_id", "")).strip()
        if not agent_id:
            raise ValueError("agent_id is required in every agent grant")
        if agent_id in agent_ids:
            raise ValueError("agent_id must be unique across agent grants")
        agent_ids.add(agent_id)
        raw_prefixes = [
            str(item).strip()
            for item in value.get("scope_prefixes", [])
            if str(item).strip()
        ]
        if any("*" in prefix for prefix in raw_prefixes):
            raise ValueError("scope_prefixes do not support wildcard characters")
        prefixes = tuple(dict.fromkeys(raw_prefixes))
        if not prefixes:
            raise ValueError("at least one scope_prefix is required")
        permissions = frozenset(
            str(item).strip()
            for item in value.get("permissions", [])
            if str(item).strip()
        )
        if not permissions or not permissions <= AGENT_PERMISSIONS:
            raise ValueError(
                "permissions must contain decide, execute, record, and/or revoke"
            )
        trust = float(value.get("trust", 0.25))
        if not 0.0 <= trust <= 1.0:
            raise ValueError("agent trust must be between 0 and 1")
        grants[digest_text] = AgentGrant(
            agent_id=agent_id,
            scope_prefixes=prefixes,
            permissions=permissions,
            trust=trust,
        )
    return grants


def authenticate_agent(
    *,
    token: str,
    grants: Mapping[str, AgentGrant],
    permission: str,
    scope_id: str,
) -> AgentGrant | None:
    if not token:
        return None
    grant = grants.get(token_digest(token))
    if grant is None or not grant.allows(permission=permission, scope_id=scope_id):
        return None
    return grant
