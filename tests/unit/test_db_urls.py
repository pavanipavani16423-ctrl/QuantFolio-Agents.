"""Neon's libpq URL is turned into what each driver expects."""

from app.db.urls import is_postgres, libpq_url, sqlalchemy_url

NEON = "postgresql://app:secret@ep-cool-1.eu-central-1.aws.neon.tech/quantfolio?sslmode=require&channel_binding=require"


def test_neon_url_for_sqlalchemy_asyncpg() -> None:
    url, args = sqlalchemy_url(NEON)
    assert url == ("postgresql+asyncpg://app:secret@ep-cool-1.eu-central-1.aws.neon.tech/quantfolio"
                   "?prepared_statement_cache_size=0")
    assert args == {"statement_cache_size": 0, "ssl": "require"}


def test_neon_url_for_psycopg_keeps_libpq_parameters() -> None:
    assert libpq_url(NEON) == NEON
    assert libpq_url("postgresql+asyncpg://u:p@h/db") == "postgresql://u:p@h/db"


def test_sqlite_is_left_alone() -> None:
    url = "sqlite+aiosqlite:///data/quantfolio.db"
    assert not is_postgres(url) and sqlalchemy_url(url) == (url, {})
    assert is_postgres("postgres://u:p@h/db") and is_postgres(NEON)
    _, args = sqlalchemy_url("postgresql://u:p@localhost/db")
    assert "ssl" not in args  # a local server without TLS
