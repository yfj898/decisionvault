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


def test_scope_prefixes_use_namespace_boundaries_instead_of_raw_startswith():
    raw_token = "opaque-agent-token"
    grants = load_agent_grants(
        json.dumps(
            {
                token_digest(raw_token): {
                    "agent_id": "recovery-observer",
                    "scope_prefixes": ["team-a"],
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
        scope_id="team-a",
    ) is not None
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
        scope_id="team-a/project",
    ) is not None
    assert authenticate_agent(
        token=raw_token,
        grants=grants,
        permission="record",
        scope_id="team-admin",
    ) is None


def test_scope_prefixes_are_deduplicated_and_wildcards_are_rejected():
    raw_token = "opaque-agent-token"
    grants = load_agent_grants(
        json.dumps(
            {
                token_digest(raw_token): {
                    "agent_id": "agent-a",
                    "scope_prefixes": [" team-a ", "team-a"],
                    "permissions": ["decide"],
                }
            }
        )
    )
    assert grants[token_digest(raw_token)].scope_prefixes == ("team-a",)

    try:
        load_agent_grants(
            json.dumps(
                {
                    token_digest(raw_token): {
                        "agent_id": "agent-a",
                        "scope_prefixes": ["team-*"],
                        "permissions": ["decide"],
                    }
                }
            )
        )
    except ValueError as exc:
        assert "wildcard" in str(exc)
    else:
        raise AssertionError("wildcard scope prefix should be rejected")


def test_duplicate_agent_identity_across_tokens_is_rejected():
    try:
        load_agent_grants(
            json.dumps(
                {
                    token_digest("token-a"): {
                        "agent_id": "same-agent",
                        "scope_prefixes": ["team-a"],
                        "permissions": ["record"],
                    },
                    token_digest("token-b"): {
                        "agent_id": "same-agent",
                        "scope_prefixes": ["team-b"],
                        "permissions": ["revoke"],
                    },
                }
            )
        )
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate agent identity should be rejected")


def test_revoke_is_a_distinct_agent_permission():
    raw_token = "revoke-token"
    grants = load_agent_grants(
        json.dumps(
            {
                token_digest(raw_token): {
                    "agent_id": "observer-a",
                    "scope_prefixes": ["team-a"],
                    "permissions": ["revoke"],
                }
            }
        )
    )
    assert authenticate_agent(
        token=raw_token,
        grants=grants,
        permission="revoke",
        scope_id="team-a-demo",
    ) is not None
    assert authenticate_agent(
        token=raw_token,
        grants=grants,
        permission="record",
        scope_id="team-a-demo",
    ) is None
