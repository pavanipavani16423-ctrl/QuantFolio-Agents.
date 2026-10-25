"""Run one A2A agent as its own service (instead of inside the API server).

    uv run python scripts/serve_agent.py risk --port 8101
    uv run python scripts/serve_agent.py compliance --port 8102

Then point the API at them:  A2A_RISK_URL=http://localhost:8101/a2a/risk  (and compliance).
The agent card is served at <url>/.well-known/agent-card.json.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app.a2a.common import add_agent_routes  # noqa: E402
from app.a2a.registry import AGENTS  # noqa: E402
from app.logging_setup import setup_logging  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("agent", choices=sorted(AGENTS))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8101)
    parser.add_argument("--public-url", help="base URL other services use to reach this one")
    args = parser.parse_args()
    setup_logging()
    module = AGENTS[args.agent]
    base = (args.public_url or f"http://{args.host}:{args.port}").rstrip("/") + f"/a2a/{args.agent}"
    app = FastAPI(title=f"QuantFolio {args.agent} agent (A2A)")
    add_agent_routes(app, module.card(base), module.executor(), f"/a2a/{args.agent}")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "agent": args.agent, "url": base}

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
