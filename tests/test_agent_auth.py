from __future__ import annotations

import json

from decisionvault.agent.auth import authenticate_agent, load_agent_grants, token_digest


def test_agent_token_binds_identity_scope_permission_and_trust():
    raw_token = "opaque-agent-token"
    grants = load_agent_grants(
        json.dumps(
            {
                token_digest(raw_token): {
                    "agent_id": "recovery-observer",
                    "scope_prefixes": ["payment-team-"],
                    "permissions": ["record"],
                    "trust": 0.8,
                }
            }
        )
    )

    grant = authenticate_agent(
        token=raw_token,
        grants=grants,
        permission="record",
        scope_id="payment-team-demo",
    )
    assert grant is not None
    assert grant.agent_id == "recovery-observer"
    assert grant.trust == 0.8
    assert authenticate_agent(
        token=raw_token,
        grants=grants,
        permission="decide",
        scope_id="payment-team-demo",
    ) is None
    assert authenticate_agent(
        token=raw_token,
        grants=grants,
        permission="record",
        scope_id="other-team",
    ) is None


def test_unknown_agent_token_is_not_authenticated():
    grants = load_agent_grants("{}")
    assert authenticate_agent(
        token="unknown",
        grants=grants,
        permission="record",
        scope_id="payment-team-demo",
    ) is None


def test_scope_prefixes_are_literal_prefixes_and_must_be_configured_with_boundary():
    raw_token = "opaque-agent-token"
    grants = load_agent_grants(
        json.dumps(
            {
                token_digest(raw_token): {
                    "agent_id": "recovery-observer",
                    "scope_prefixes": ["team-a-"],
                    "permissions": ["record"],
                    "trust": 0.8,
                }
            }
        )
    )

    assert authenticate_agent(
        token=raw_token,
        grants=grants,
        permission="record",
        scope_id="team-a-demo",
    ) is not None
    assert authenticate_agent(
        token=raw_token,
        grants=grants,
        permission="record",
        scope_id="team-admin",
    ) is None
