from __future__ import annotations

from collections.abc import Callable
import os


def psycopg_connection_factory(
    database_url: str | None = None,
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

    def connect() -> object:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - environment-specific
            raise RuntimeError(
                'CockroachDB Cloud support requires the "cloud" extra: '
                'uv pip install -e ".[cloud]"'
            ) from exc

        return psycopg.connect(url)

    return connect
