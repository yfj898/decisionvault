from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from uuid import uuid4

from decisionvault.domain import Outcome, Strategy
from decisionvault.execution import (
    DECISION_CONTRACT_REVISION,
    issue_external_receipt,
    verify_execution_receipt,
)
from decisionvault.execution_adapters import GitHubContentsExecutionAdapter


DEFAULT_REPOSITORY = "yfj898/decisionvault-execution-sandbox"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create and verify one deterministic GitHub repository-file side effect, "
            "replay the same "
            "snapshot idempotently, and bind the proof into a signed v3 receipt."
        )
    )
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument(
        "--strategy",
        choices=tuple(item.value for item in Strategy),
        default=Strategy.REFRESH_PAYMENT_TOKEN.value,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/github-execution-smoke.json"),
    )
    args = parser.parse_args()
    if args.repository != DEFAULT_REPOSITORY:
        raise SystemExit("repository must remain the source-allowlisted test repository")

    token = os.getenv("GITHUB_EXECUTION_TOKEN", "").strip()
    if not token:
        raise SystemExit("GITHUB_EXECUTION_TOKEN is required")

    snapshot_id = str(uuid4())
    strategy = Strategy(args.strategy)
    adapter = GitHubContentsExecutionAdapter(token=token, repository=args.repository)
    first = adapter.execute(
        decision_snapshot_id=snapshot_id,
        strategy=strategy,
    )
    replay = adapter.execute(
        decision_snapshot_id=snapshot_id,
        strategy=strategy,
    )
    if first.external_operation_id != replay.external_operation_id:
        raise RuntimeError("GitHub execution replay created a different operation")
    if not bool(replay.evidence.get("idempotent_replay")):
        raise RuntimeError("GitHub execution replay was not recognized as idempotent")

    signing_secret = os.getenv("EXECUTION_RECEIPT_SECRET", "").strip()
    if len(signing_secret) < 16:
        signing_secret = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    receipt_payload = issue_external_receipt(
        scope_id="execution-proof",
        agent_id="github-execution-smoke",
        situation="test-only governed remediation dispatch",
        strategy=strategy,
        execution_provider=first.provider,
        external_operation_id=first.external_operation_id,
        execution_evidence=first.evidence,
        outcome=first.outcome,
        effectiveness=first.effectiveness,
        confidence=first.confidence,
        signing_secret=signing_secret,
        decision_snapshot_id=snapshot_id,
        decision_digest="0" * 64,
        decision_revision=DECISION_CONTRACT_REVISION,
        decision_agent_id="github-execution-smoke-planner",
        now=now,
    )
    receipt = verify_execution_receipt(
        receipt_payload,
        signing_secret=signing_secret,
        expected_scope_id="execution-proof",
        expected_agent_id="github-execution-smoke",
        now=now,
    )
    if receipt.outcome != Outcome.UNKNOWN:
        raise RuntimeError("external execution proof must not claim business success")

    payload = {
        "repository": args.repository,
        "provider": first.provider,
        "external_operation_id": first.external_operation_id,
        "resource_path": str(first.evidence["path"]),
        "blob_sha": str(first.evidence["blob_sha"]),
        "first_execution_verified": bool(first.evidence["verified"]),
        "idempotent_replay_verified": bool(replay.evidence["idempotent_replay"]),
        "receipt_version": receipt.version,
        "receipt_verified": True,
        "business_outcome": receipt.outcome.value,
        "business_outcome_verified": False,
        "automatic_memory_success_claim": False,
        "generated_at": now.isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"github_repository={args.repository}")
    print(f"external_operation_id={first.external_operation_id}")
    print(f"resource_path={payload['resource_path']}")
    print(f"blob_sha={payload['blob_sha']}")
    print("first_execution_verified=PASS")
    print("idempotent_replay=PASS")
    print("external_receipt_v3=PASS")
    print("business_outcome_verified=False")
    print("github_execution_smoke=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
