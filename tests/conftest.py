"""Test isolation: never touch the real database, broker ledger, LLM or Langfuse project.

Set TEST_DATABASE_URL to an empty Postgres database to run the same tests against Postgres (the
cloud setup: runs, memory, audit, checkpoints, broker ledger and added clients all in it).
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="quantfolio-tests-"))
_POSTGRES = os.environ.get("TEST_DATABASE_URL")

# environment variables win over .env in pydantic-settings
os.environ.update({
    "DATABASE_URL": _POSTGRES or f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}",
    "CHECKPOINT_DB": str(_TMP / "checkpoints.db"),
    "PAPER_BROKER_DB": str(_TMP / "broker.db"),
    "CLIENTS_DIR": str(_TMP / "clients"),
    "LLM_PROVIDER": "mock",
    "GROQ_API_KEY": "",
    "LANGFUSE_PUBLIC_KEY": "",
    "LANGFUSE_SECRET_KEY": "",
    "RATE_LIMIT_RUNS": "1000",
    "PUBLIC_BASE_URL": "http://127.0.0.1:9",  # nothing listens: A2A uses the in-process fallback
})
if _POSTGRES and sys.platform == "win32":
    # psycopg's async driver cannot use Windows' default Proactor event loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest  # noqa: E402


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def tmp_dir() -> Path:
    return _TMP
