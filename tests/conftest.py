"""Test isolation: never touch the real database, broker ledger, LLM or Langfuse project."""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="quantfolio-tests-"))

# environment variables win over .env in pydantic-settings
os.environ.update({
    "DATABASE_URL": f"sqlite+aiosqlite:///{(_TMP / 'test.db').as_posix()}",
    "CHECKPOINT_DB": str(_TMP / "checkpoints.db"),
    "PAPER_BROKER_DB": str(_TMP / "broker.db"),
    "LLM_PROVIDER": "mock",
    "GROQ_API_KEY": "",
    "LANGFUSE_PUBLIC_KEY": "",
    "LANGFUSE_SECRET_KEY": "",
    "QAOA_MAXITER": "25",
    "PUBLIC_BASE_URL": "http://127.0.0.1:9",  # nothing listens: A2A uses the in-process fallback
})

import pytest  # noqa: E402


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def tmp_dir() -> Path:
    return _TMP
