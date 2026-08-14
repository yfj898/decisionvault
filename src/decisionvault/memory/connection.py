from __future__ import annotations

from collections.abc import Callable
import os


def psycopg_connection_factory(
    database_url: str | None = None,
    *,
    connect_timeout_seconds: int | None = None,
    statement_timeout_ms: int | None = None,
) -> Callable[[], object]:
    """Build a lazy CockroachDB connection factory.

    The URL is resolved once, but the database connection itself is created for
    every store operation. This keeps the adapter compatible with short-lived
    workers such as Lambda and makes persistence tests use fresh connections.
    """

    url = database_url or os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "DATABASE_URL is required for CockroachDB Cloud persistence"
        )

    connect_timeout = int(
        connect_timeout_seconds
        if connect_timeout_seconds is not None
        else os.getenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "5")
    )
    statement_timeout = int(
        statement_timeout_ms
        if statement_timeout_ms is not None
        else os.getenv("DATABASE_STATEMENT_TIMEOUT_MS", "8000")
    )
    if connect_timeout <= 0 or statement_timeout <= 0:
        raise ValueError("database timeout values must be positive")

    def connect() -> object:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise RuntimeError(
                'CockroachDB Cloud support requires the "cloud" extra: '
                'uv pip install -e ".[cloud]"'
            ) from exc

        return psycopg.connect(
            url,
            connect_timeout=connect_timeout,
            options=f"-c statement_timeout={statement_timeout}",
        )

    return connect
