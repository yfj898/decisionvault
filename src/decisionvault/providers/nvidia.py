from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from urllib.request import Request

from decisionvault.domain import Decision, RecalledEpisode
from decisionvault.providers.http_security import (
    NVIDIA_API_BASE_URL,
    nvidia_endpoint,
    open_nvidia_request,
    validate_nvidia_base_url,
)


@dataclass(slots=True)
class NvidiaDecisionAdvisor:
    api_key: str
    model_id: str = "deepseek-ai/deepseek-v4-flash-0731"
    base_url: str = NVIDIA_API_BASE_URL
    timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        self.base_url = validate_nvidia_base_url(self.base_url)

    @property
    def provider_name(self) -> str:
        return f"nvidia:{self.model_id}"

    def explain(
        self,
        *,
        situation: str,
        decision: Decision,
        recalled: list[RecalledEpisode],
    ) -> str:
        memory_lines = [
            (
                f"episode={item.episode.episode_id}; "
                f"strategy={item.episode.strategy.value}; "
                f"outcome={item.episode.outcome.value}; "
                f"effectiveness={item.episode.effectiveness:.2f}; "
                f"similarity={item.similarity:.3f}"
            )
            for item in recalled[:5]
        ]
        memory_block = "\n".join(memory_lines) or "none"
        committed_strategy = (
            decision.strategy.value if decision.strategy is not None else "NONE"
        )
        trace = json.dumps(
            asdict(decision.governance_trace),
            sort_keys=True,
            separators=(",", ":"),
        )
        prompt = (
            f"Situation: {situation}\n"
            f"Committed strategy: {committed_strategy}\n"
            f"Deterministic reason: {decision.reason}\n"
            f"Governance trace: {trace}\n"
            f"Selected governed memory IDs: {list(decision.recalled_memory_ids)}\n"
            f"Recalled memory evidence:\n{memory_block}\n\n"
            "In at most 60 words, explain the already-committed governance trace "
            "and why the committed strategy is consistent with the admitted "
            "evidence. Do not recommend another strategy or alter the trace."
        )
        body = json.dumps(
            {
                "model": self.model_id,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are an explanation-only component. The strategy "
                            "is already committed and cannot be changed."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0,
                "max_tokens": 180,
            }
        ).encode("utf-8")
        request = Request(
            nvidia_endpoint(self.base_url, "chat/completions"),
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with open_nvidia_request(
            request, timeout_seconds=self.timeout_seconds
        ) as response:
            payload = json.loads(response.read())
        return payload["choices"][0]["message"]["content"].strip()
