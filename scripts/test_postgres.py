"""Run the test suite against a throwaway Postgres server (no Docker needed).

    uv run --with pgserver python scripts/test_postgres.py [pytest args]

pgserver ships Postgres binaries as a Python package; the server lives in a temp folder and is
stopped afterwards. CI uses a Postgres service container instead (TEST_DATABASE_URL).
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pgserver

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    server = pgserver.get_server(tempfile.mkdtemp(prefix="quantfolio-pg-"), cleanup_mode="stop")
    server.psql("CREATE DATABASE quantfolio_test;")
    url = server.get_uri("quantfolio_test")
    print(f"Postgres: {url}", flush=True)
    env = {**os.environ, "TEST_DATABASE_URL": url}
    return subprocess.run([sys.executable, "-m", "pytest", *(sys.argv[1:] or ["tests"])], cwd=ROOT, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
