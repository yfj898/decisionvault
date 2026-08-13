from __future__ import annotations

from dataclasses import dataclass
import json
from urllib.request import Request, urlopen

from decisionvault.domain import Decision, RecalledEpisode


@dataclass(slots=True)
class NvidiaDecisionAdvisor:
    api_key: str
    model_id: str = "deepseek-ai/deepseek-v4-flash-0731"
    base_url: str = "https://integrate.api.nvidia.com/v1"
    timeout_seconds: float = 45.0

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
        prompt = (
            f"Situation: {situation}\n"
            f"Committed strategy: {decision.strategy.value}\n"
            f"Deterministic reason: {decision.reason}\n"
            f"Recalled memory evidence:\n{memory_block}\n\n"
            "In at most 60 words, explain why the committed strategy is "
            "consistent with the recalled outcomes. Do not recommend another "
            "strategy."
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
            f"{self.base_url.rstrip('/')}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            payload = json.loads(response.read())
        return payload["choices"][0]["message"]["content"].strip()
