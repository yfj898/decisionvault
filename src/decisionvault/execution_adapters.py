from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import re
import time
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from decisionvault.domain import Outcome, Strategy


GITHUB_EXECUTION_PROVIDER = "github-contents-v1"
GITHUB_API_ORIGIN = "https://api.github.com"
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_MAX_RESPONSE_BYTES = 512 * 1024


class ExternalExecutionUnavailable(RuntimeError):
    """The server-bound external execution provider could not be verified."""


class _GitHubExecutionHTTPError(ExternalExecutionUnavailable):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"GitHub execution API returned HTTP {status_code}")
        self.status_code = int(status_code)


@dataclass(frozen=True, slots=True)
class ExternalExecutionResult:
    provider: str
    external_operation_id: str
    outcome: Outcome
    effectiveness: float
    confidence: float
    evidence: Mapping[str, Any]


class ExecutionAdapter(Protocol):
    @property
    def provider_name(self) -> str: ...

    def execute(
        self,
        *,
        decision_snapshot_id: str,
        strategy: Strategy,
    ) -> ExternalExecutionResult: ...


@dataclass(slots=True)
class GitHubContentsExecutionAdapter:
    """Create one deterministic file per snapshot in a server-bound test repo.

    GitHub issues do not expose a first-class idempotency key and their listing
    can lag immediately after creation. The Contents API gives each snapshot a
    deterministic resource path instead. A second create for the same path is
    rejected by GitHub, so retries reconcile by reading that exact path rather
    than by searching an eventually-consistent issue list.
    """

    token: str
    repository: str
    timeout_seconds: float = 8.0

    def __post_init__(self) -> None:
        self.token = self.token.strip()
        self.repository = self.repository.strip()
        if not self.token:
            raise ValueError("GitHub execution token is required")
        if not _REPOSITORY_RE.fullmatch(self.repository):
            raise ValueError("GitHub execution repository must be owner/name")
        if not 0.5 <= float(self.timeout_seconds) <= 12.0:
            raise ValueError("GitHub execution timeout must be between 0.5 and 12 seconds")

    @property
    def provider_name(self) -> str:
        return GITHUB_EXECUTION_PROVIDER

    @property
    def _repo_path(self) -> str:
        owner, name = self.repository.split("/", 1)
        return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"

    def _json_request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        if not path.startswith("/repos/"):
            raise ValueError("GitHub execution path must stay under /repos")
        body = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "DecisionVault-Execution-Adapter/1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(
            GITHUB_API_ORIGIN + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=float(self.timeout_seconds)) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise _GitHubExecutionHTTPError(int(exc.code)) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ExternalExecutionUnavailable(
                "GitHub execution API is unavailable"
            ) from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise RuntimeError("GitHub execution API response exceeded size limit")
        return json.loads(raw) if raw else None

    @staticmethod
    def _resource_path(snapshot_id: str) -> str:
        return f"decisionvault-executions/{snapshot_id}.json"

    @staticmethod
    def _document(snapshot_id: str, strategy: Strategy) -> dict[str, Any]:
        return {
            "schema": "decisionvault-external-execution-v1",
            "decision_snapshot_id": snapshot_id,
            "committed_strategy": strategy.value,
            "purpose": "test-only governed external side-effect proof",
            "contains_customer_data": False,
            "business_outcome_verified": False,
        }

    @classmethod
    def _document_bytes(cls, snapshot_id: str, strategy: Strategy) -> bytes:
        return (
            json.dumps(
                cls._document(snapshot_id, strategy),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

    def _content_api_path(self, snapshot_id: str) -> str:
        path = self._resource_path(snapshot_id)
        return f"{self._repo_path}/contents/{quote(path, safe='/')}"

    def _get_existing(self, *, snapshot_id: str) -> Mapping[str, Any] | None:
        try:
            payload = self._json_request("GET", self._content_api_path(snapshot_id))
        except _GitHubExecutionHTTPError as exc:
            if exc.status_code == 404:
                return None
            raise
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub content lookup response is invalid")
        return payload

    def _get_existing_with_retry(
        self,
        *,
        snapshot_id: str,
        attempts: int = 5,
    ) -> Mapping[str, Any] | None:
        """Bound read-after-write propagation without ever repeating the PUT."""

        for attempt in range(max(1, attempts)):
            existing = self._get_existing(snapshot_id=snapshot_id)
            if existing is not None:
                return existing
            if attempt + 1 < attempts:
                time.sleep(min(1.0, 0.2 * (2**attempt)))
        return None

    def _verify_file(
        self,
        *,
        payload: Mapping[str, Any],
        snapshot_id: str,
        strategy: Strategy,
        replay: bool,
    ) -> ExternalExecutionResult:
        if str(payload.get("type", "")) != "file":
            raise RuntimeError("GitHub execution resource is not a file")
        path = str(payload.get("path", ""))
        if path != self._resource_path(snapshot_id):
            raise RuntimeError("GitHub execution resource path does not match snapshot")
        if str(payload.get("encoding", "")) != "base64":
            raise RuntimeError("GitHub execution resource encoding is unsupported")
        try:
            decoded = base64.b64decode(str(payload.get("content", "")), validate=False)
        except (ValueError, TypeError) as exc:
            raise RuntimeError("GitHub execution resource content is invalid") from exc
        if decoded != self._document_bytes(snapshot_id, strategy):
            raise RuntimeError("GitHub execution resource content does not match decision")
        blob_sha = str(payload.get("sha", "")).strip()
        if not blob_sha:
            raise RuntimeError("GitHub execution resource is missing blob sha")
        return ExternalExecutionResult(
            provider=self.provider_name,
            external_operation_id=f"github:{self.repository}:{path}@{blob_sha}",
            # This verifies that the external side effect happened. It does not
            # claim that the payment-recovery strategy itself succeeded; that
            # requires a separate business-outcome verifier.
            outcome=Outcome.UNKNOWN,
            effectiveness=0.0,
            confidence=1.0,
            evidence={
                "verified": True,
                "object_type": "github_repository_file",
                "repository": self.repository,
                "path": path,
                "blob_sha": blob_sha,
                "idempotent_replay": bool(replay),
            },
        )

    def execute(
        self,
        *,
        decision_snapshot_id: str,
        strategy: Strategy,
    ) -> ExternalExecutionResult:
        snapshot_id = decision_snapshot_id.strip()
        if not snapshot_id:
            raise ValueError("decision snapshot id is required for GitHub execution")
        existing = self._get_existing(snapshot_id=snapshot_id)
        if existing is not None:
            return self._verify_file(
                payload=existing,
                snapshot_id=snapshot_id,
                strategy=strategy,
                replay=True,
            )

        create_payload = {
            "message": f"decisionvault: execute snapshot {snapshot_id}",
            "content": base64.b64encode(
                self._document_bytes(snapshot_id, strategy)
            ).decode("ascii"),
        }
        reconciled_replay = False
        try:
            self._json_request("PUT", self._content_api_path(snapshot_id), create_payload)
        except _GitHubExecutionHTTPError as exc:
            if exc.status_code not in {409, 422}:
                raise
            # A concurrent/replayed create cannot create a second resource at
            # the same deterministic path. Read that exact resource and verify.
            reconciled_replay = True
        except ExternalExecutionUnavailable:
            # The PUT may have committed before a network timeout. Exact-path
            # reconciliation determines whether the side effect exists.
            reconciled_replay = True

        reconciled = self._get_existing_with_retry(snapshot_id=snapshot_id)
        if reconciled is None:
            raise ExternalExecutionUnavailable(
                "GitHub execution could not verify the deterministic resource"
            )
        return self._verify_file(
            payload=reconciled,
            snapshot_id=snapshot_id,
            strategy=strategy,
            replay=reconciled_replay,
        )
