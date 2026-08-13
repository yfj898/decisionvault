from __future__ import annotations

from dataclasses import dataclass
import json

from decisionvault.domain import Decision, RecalledEpisode


@dataclass(slots=True)
class BedrockTextProvider:
    """Minimal Bedrock seam.

    boto3 is imported lazily so local tests do not need AWS dependencies.
    A real smoke test is required before any competition claim is made.
    """

    model_id: str
    region_name: str = "us-east-1"

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
        prompt = (
            f"Situation: {situation}\n"
            f"Committed strategy: {decision.strategy.value}\n"
            f"Deterministic reason: {decision.reason}\n"
            f"Recalled memory evidence:\n{memory_block}\n\n"
            "In at most 60 words, explain why the committed strategy is "
            "consistent with the recalled outcomes. Do not recommend another "
            "strategy."
        )
        return self.provider.converse_text(prompt)
