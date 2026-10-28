"""A shared synchronous Postgres pool for the parts that are not SQLAlchemy (the paper broker,
clients added in the UI). Only used when DATABASE_URL points at Postgres."""

import threading

from app.config import get_settings
from app.db.urls import libpq_url

_POOL = None
_LOCK = threading.Lock()


def pool():  # noqa: ANN201
    global _POOL
    with _LOCK:
        if _POOL is None:
            from psycopg_pool import ConnectionPool

            # prepare_threshold=None: no server-side prepared statements (PgBouncer-safe);
            # check: a connection closed by Neon's auto-suspend is replaced, not handed out
            _POOL = ConnectionPool(libpq_url(get_settings().database_url), min_size=0, max_size=4,
                                   kwargs={"autocommit": True, "prepare_threshold": None},
                                   check=ConnectionPool.check_connection, open=True)
        return _POOL
