from __future__ import annotations

import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


NVIDIA_API_BASE_URL = "https://integrate.api.nvidia.com/v1"

# Server-side or throttle responses that are safe to retry once: the response
# has already arrived, so no timeout budget was consumed, and the request is
# idempotent (deterministic completions / deterministic embeddings).
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})


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


def open_nvidia_request(
    request: Request,
    *,
    timeout_seconds: float,
    retry_attempts: int = 1,
    retry_delay_seconds: float = 1.0,
):
    """Open a validated NVIDIA request without cross-origin redirect forwarding.

    Fast-failure errors (HTTP 429/5xx, connection-level failures) are retried
    once with a short delay. Timeout errors are NOT retried: the timeout budget
    is already consumed, and the Lambda deadline must remain guaranteed.
    """

    allowed_urls = {
        f"{NVIDIA_API_BASE_URL}/embeddings",
        f"{NVIDIA_API_BASE_URL}/chat/completions",
    }
    if request.full_url not in allowed_urls:
        raise ValueError("refusing NVIDIA credential forwarding to a non-allowlisted URL")
    opener = build_opener(_RejectRedirects())
    attempts = 1 + max(0, int(retry_attempts))
    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            return opener.open(request, timeout=timeout_seconds)
        except (HTTPError, URLError) as exc:
            last_error = exc
            if attempt + 1 >= attempts or not _is_retryable_open_error(exc):
                raise
            time.sleep(retry_delay_seconds)
    if last_error is not None:
        raise last_error
    raise AssertionError("unreachable")


def _is_retryable_open_error(exc: HTTPError | URLError) -> bool:
    """True for failures that arrived fast and are safe to retry idempotently.

    Timeout errors are excluded: the caller's timeout budget is already spent,
    and a retry would exceed the Lambda deadline instead of healing it.
    """

    if isinstance(exc, HTTPError):
        return exc.code in _RETRYABLE_HTTP_CODES
    if isinstance(exc, URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            # socket.timeout is an alias of TimeoutError since Python 3.10.
            return False
        # ConnectionRefusedError, ConnectionResetError, gaierror (DNS), etc.
        return isinstance(reason, (ConnectionError, OSError))
    return False


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
