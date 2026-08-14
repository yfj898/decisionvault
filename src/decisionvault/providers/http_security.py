from __future__ import annotations

from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


NVIDIA_API_BASE_URL = "https://integrate.api.nvidia.com/v1"


def validate_nvidia_base_url(value: str | None) -> str:
    """Return the one allowed NVIDIA API base URL or fail closed.

    ``NVIDIA_API_KEY`` is a bearer credential. Allowing a deploy-time environment
    variable to redirect bearer-authenticated traffic would turn the Lambda into
    a confused deputy. Keep the variable only as a compatibility/configuration
    assertion: it may be omitted or equal the canonical NVIDIA API URL (with an
    optional trailing slash), but it cannot select another origin, port, path,
    query, fragment, or userinfo component.
    """

    candidate = (value or NVIDIA_API_BASE_URL).strip()
    if candidate.rstrip("/") != NVIDIA_API_BASE_URL:
        raise ValueError(
            "NVIDIA_BASE_URL must resolve to the fixed DecisionVault NVIDIA provider origin"
        )
    return NVIDIA_API_BASE_URL


def nvidia_endpoint(base_url: str | None, endpoint: str) -> str:
    canonical_base = validate_nvidia_base_url(base_url)
    normalized_endpoint = endpoint.strip().lstrip("/")
    if normalized_endpoint not in {"embeddings", "chat/completions"}:
        raise ValueError("unsupported NVIDIA API endpoint")
    return f"{canonical_base}/{normalized_endpoint}"


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        raise HTTPError(
            req.full_url,
            code,
            "NVIDIA credential-bearing requests must not follow redirects",
            headers,
            fp,
        )


def open_nvidia_request(request: Request, *, timeout_seconds: float):
    """Open a validated NVIDIA request without cross-origin redirect forwarding."""

    allowed_urls = {
        f"{NVIDIA_API_BASE_URL}/embeddings",
        f"{NVIDIA_API_BASE_URL}/chat/completions",
    }
    if request.full_url not in allowed_urls:
        raise ValueError("refusing NVIDIA credential forwarding to a non-allowlisted URL")
    return build_opener(_RejectRedirects()).open(request, timeout=timeout_seconds)


def open_fixed_bearer_request(
    request: Request,
    *,
    allowed_url: str,
    timeout_seconds: float,
):
    """Open an exact bearer-authenticated endpoint without following redirects."""

    if request.full_url != allowed_url:
        raise ValueError("refusing bearer credential forwarding to a non-allowlisted URL")
    return build_opener(_RejectRedirects()).open(request, timeout=timeout_seconds)
