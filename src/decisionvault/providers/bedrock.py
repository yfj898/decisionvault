from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
from urllib.parse import quote

from decisionvault.domain import Decision, RecalledEpisode
from decisionvault.providers.http_security import open_fixed_bearer_request


@dataclass(slots=True)
class BedrockTextProvider:
    """Minimal Bedrock seam.

    boto3 is imported lazily so local tests do not need AWS dependencies.
    A real smoke test is required before any competition claim is made.
    """

    model_id: str
    region_name: str = "us-east-1"

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9-]+", self.region_name):
            raise ValueError("Bedrock region contains unsupported characters")
        if not self.model_id.strip():
            raise ValueError("Bedrock model_id is required")

    def invoke_json(self, payload: dict) -> dict:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=self.region_name)
        response = client.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(payload).encode("utf-8"),
        )
        return json.loads(response["body"].read())

    def converse_text(
        self,
        prompt: str,
        *,
        max_tokens: int = 180,
        temperature: float = 0.0,
    ) -> str:
        bearer_token = os.getenv("AWS_BEARER_TOKEN_BEDROCK", "").strip()
        if bearer_token:
            from urllib.request import Request

            endpoint = (
                f"https://bedrock-runtime.{self.region_name}.amazonaws.com/"
                f"model/{quote(self.model_id, safe='')}/converse"
            )
            request = Request(
                url=endpoint,
                headers={
                    "Authorization": f"Bearer {bearer_token}",
                    "Content-Type": "application/json",
                },
                data=json.dumps({
                    "system": [
                        {
                            "text": (
                                "You are a bounded decision explanation component. "
                                "Explain the already-committed strategy using only "
                                "the provided memory evidence. Never propose or "
                                "select a different strategy."
                            )
                        }
                    ],
                    "messages": [
                        {"role": "user", "content": [{"text": prompt}]}
                    ],
                    "inferenceConfig": {
                        "maxTokens": max_tokens,
                        "temperature": temperature,
                    },
                }).encode("utf-8"),
                method="POST",
            )
            with open_fixed_bearer_request(
                request,
                allowed_url=endpoint,
                timeout_seconds=30,
            ) as response:
                payload = json.loads(response.read())
            parts = payload["output"]["message"]["content"]
            return " ".join(
                part["text"].strip()
                for part in parts
                if isinstance(part, dict) and part.get("text")
            ).strip()

        import boto3

        client = boto3.client("bedrock-runtime", region_name=self.region_name)
        response = client.converse(
            modelId=self.model_id,
            system=[
                {
                    "text": (
                        "You are a bounded decision explanation component. "
                        "Explain the already-committed strategy using only the "
                        "provided memory evidence. Never propose or select a "
                        "different strategy."
                    )
                }
            ],
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": max_tokens,
                "temperature": temperature,
            },
        )
        parts = response["output"]["message"]["content"]
        return " ".join(
            part["text"].strip()
            for part in parts
            if isinstance(part, dict) and part.get("text")
        ).strip()


@dataclass(slots=True)
class BedrockDecisionAdvisor:
    provider: BedrockTextProvider

    @property
    def provider_name(self) -> str:
        return f"bedrock:{self.provider.model_id}"

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
        prompt = (
            f"Situation: {situation}\n"
            f"Committed strategy: {committed_strategy}\n"
            f"Deterministic reason: {decision.reason}\n"
            f"Recalled memory evidence:\n{memory_block}\n\n"
            "In at most 60 words, explain why the committed strategy is "
            "consistent with the recalled outcomes. Do not recommend another "
            "strategy."
        )
        return self.provider.converse_text(prompt)
