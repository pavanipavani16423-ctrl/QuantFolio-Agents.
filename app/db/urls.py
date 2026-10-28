"""Database URLs: SQLite on a laptop, Postgres (for example Neon) in the cloud.

Neon hands out a libpq URL: `postgresql://user:pass@host/db?sslmode=require&channel_binding=require`.
psycopg (the LangGraph checkpointer, the paper broker, added clients) takes it as is. asyncpg
(SQLAlchemy) does not understand libpq parameters, so `sslmode` becomes a connect argument and
the rest is dropped. Prepared-statement caches are off on both drivers, so Neon's pooled
endpoint (PgBouncer in transaction mode) works too.
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LIBPQ_ONLY = frozenset({"sslmode", "channel_binding", "options", "target_session_attrs", "sslrootcert"})


def is_postgres(url: str) -> bool:
    return url.split(":", 1)[0].split("+", 1)[0] in ("postgres", "postgresql")


def sqlalchemy_url(url: str) -> tuple[str, dict]:
    """The SQLAlchemy URL (asyncpg for Postgres) and its connect arguments."""
    if not is_postgres(url):
        return url, {}
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    kept = {k: v for k, v in query.items() if k not in LIBPQ_ONLY}
    kept["prepared_statement_cache_size"] = "0"
    connect_args: dict = {"statement_cache_size": 0}
    if query.get("sslmode", "prefer") not in ("disable", "allow", "prefer"):
        connect_args["ssl"] = "require"
    return urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, urlencode(kept), "")), connect_args


def libpq_url(url: str) -> str:
    """The URL psycopg expects (any SQLAlchemy driver suffix removed)."""
    parts = urlsplit(url)
    return urlunsplit(("postgresql", parts.netloc, parts.path, parts.query, ""))
