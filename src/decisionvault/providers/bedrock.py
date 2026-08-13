from __future__ import annotations

from dataclasses import dataclass
import json


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
