"""Deploy on free tiers: Neon (Postgres), Hugging Face Spaces (Docker backend), Vercel (UI).

    uv run --with huggingface_hub python scripts/deploy.py              # everything
    uv run --with huggingface_hub python scripts/deploy.py --only space # one part

Tokens come from .env.deploy (git-ignored): HF_TOKEN, NEON_API_KEY, VERCEL_TOKEN. App secrets
(GROQ_API_KEY, LANGFUSE_*) come from .env. Nothing secret is printed or committed; the Neon URL
and the approval key are kept in .env.deploy. Running it again updates the same Neon project,
Space and Vercel project instead of creating new ones.
"""

import argparse
import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_ENV = ROOT / ".env.deploy"
SPACE_NAME = "quantfolio-api"
VERCEL_PROJECT = "quantfolio-agents"
NEON_PROJECT = "quantfolio"
NEON_REGION = "aws-ap-southeast-1"  # Singapore; Hugging Face's free CPUs run in the US/EU
# what the backend image needs (tracked files only, see `git ls-files`)
SPACE_PATHS = ["Dockerfile", ".dockerignore", "pyproject.toml", "uv.lock", "app", "data", "scripts",
               "experiments/results"]

SPACE_README = """---
title: QuantFolio Agents API
emoji: 📈
colorFrom: yellow
colorTo: red
sdk: docker
app_port: 8000
pinned: false
short_description: Multi-agent investment research API (hybrid RAG, A2A, MCP)
---

Backend of [QuantFolio Agents]({repo}): FastAPI with the LangGraph agents and the hosted A2A
risk and compliance agents. Built from the `Dockerfile` of the GitHub repository by
`scripts/deploy.py`. The UI runs on Vercel and the database on Neon.

* Health: `/health`
* Agent cards: `/a2a/risk/.well-known/agent-card.json`, `/a2a/compliance/.well-known/agent-card.json`
* API: `/api/v1/...`
"""


# ---- helpers ------------------------------------------------------------------------------
def read_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        if value:
            out[key.strip()] = value
    return out


def remember(key: str, value: str) -> None:
    """Store a generated value (Neon URL, approval key) in .env.deploy, replacing an older one."""
    lines = DEPLOY_ENV.read_text("utf-8").splitlines() if DEPLOY_ENV.exists() else []
    lines = [ln for ln in lines if not ln.startswith(f"{key}=")] + [f"{key}={value}"]
    DEPLOY_ENV.write_text("\n".join(lines) + "\n", "utf-8")


def http(method: str, url: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {url.split('?')[0]} failed: {exc.code} {exc.read()[:300]!r}") from None


def step(text: str) -> None:
    print(f"\n== {text}", flush=True)


# ---- Neon ---------------------------------------------------------------------------------
def neon(cfg: dict[str, str]) -> str:
    step("Neon: Postgres database")
    key, api = cfg["NEON_API_KEY"], "https://console.neon.tech/api/v2"
    projects = http("GET", f"{api}/projects?search={NEON_PROJECT}", key).get("projects", [])
    project = next((p for p in projects if p["name"] == NEON_PROJECT), None)
    if project is None:
        created = http("POST", f"{api}/projects", key,
                       {"project": {"name": NEON_PROJECT, "region_id": NEON_REGION, "pg_version": 17}})
        project = created["project"]
        print(f"created project {project['id']} in {project['region_id']}")
    else:
        print(f"using project {project['id']} in {project['region_id']}")
    branches = http("GET", f"{api}/projects/{project['id']}/branches", key)["branches"]
    branch = next(b for b in branches if b.get("default") or b.get("primary"))
    roles = http("GET", f"{api}/projects/{project['id']}/branches/{branch['id']}/roles", key)["roles"]
    role = next(r["name"] for r in roles if not r.get("protected"))
    dbs = http("GET", f"{api}/projects/{project['id']}/branches/{branch['id']}/databases", key)["databases"]
    database = dbs[0]["name"]
    uri = http("GET", f"{api}/projects/{project['id']}/connection_uri?branch_id={branch['id']}"
                      f"&database_name={database}&role_name={role}&pooled=false", key)["uri"]
    remember("DATABASE_URL", uri)
    print(f"database {database}, role {role}; connection string saved to .env.deploy")
    return uri


# ---- Hugging Face Space -------------------------------------------------------------------
def space(cfg: dict[str, str], app_env: dict[str, str], database_url: str) -> str:
    from huggingface_hub import HfApi

    step("Hugging Face Space: Docker backend")
    api = HfApi(token=cfg["HF_TOKEN"])
    owner = api.whoami()["name"]
    repo_id = f"{owner}/{SPACE_NAME}"
    api.create_repo(repo_id, repo_type="space", space_sdk="docker", exist_ok=True)
    host = f"https://{re.sub(r'[^a-z0-9]+', '-', owner.lower())}-{SPACE_NAME}.hf.space"

    approval = cfg.get("APPROVAL_SECRET") or secrets.token_urlsafe(32)
    remember("APPROVAL_SECRET", approval)
    variables = {
        "LLM_PROVIDER": app_env.get("LLM_PROVIDER", "groq"),
        "LANGFUSE_BASE_URL": app_env.get("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
        "LANGFUSE_ENVIRONMENT": "production",
        "PUBLIC_BASE_URL": host,
        "CORS_ORIGINS": json.dumps(cfg.get("CORS_ORIGINS_LIST", "").split() or ["https://quantfolio-agents.vercel.app"]),
        # the production address and its preview deployments
        "CORS_ORIGIN_REGEX": r"https://quantfolio-agents(-[a-z0-9-]+)?\.vercel\.app",
    }
    space_secrets = {"DATABASE_URL": database_url, "APPROVAL_SECRET": approval}
    for key in ("GROQ_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "JUDGE_MODEL", "LLM_MODEL"):
        if app_env.get(key):
            space_secrets[key] = app_env[key]
    for key, value in variables.items():
        api.add_space_variable(repo_id, key, value)
    for key, value in space_secrets.items():
        api.add_space_secret(repo_id, key, value)
    print(f"set {len(variables)} variables and {len(space_secrets)} secrets ({', '.join(space_secrets)})")

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp)
        files = subprocess.run(["git", "ls-files", *SPACE_PATHS], cwd=ROOT, capture_output=True, text=True,
                               check=True).stdout.splitlines()
        for name in files:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, target)
        repo = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True,
                              text=True).stdout.strip().split("@")[-1].removesuffix(".git")
        (stage / "README.md").write_text(SPACE_README.format(repo=f"https://{repo}"), "utf-8")
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True).stdout.strip()
        api.upload_folder(repo_id=repo_id, repo_type="space", folder_path=stage, delete_patterns="*",
                          commit_message=f"Deploy {commit}")
    print(f"uploaded {len(files)} files from commit {commit}; building")

    started = time.time()
    while True:
        stage_name = api.get_space_runtime(repo_id).stage
        if stage_name == "RUNNING":
            break
        if stage_name in ("BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE"):
            raise SystemExit(f"Space failed: {stage_name}. Logs: https://huggingface.co/spaces/{repo_id}?logs=build")
        if time.time() - started > 3600:
            raise SystemExit("Space still not running after an hour")
        print(f"  {stage_name} ({int(time.time() - started)} s)", flush=True)
        time.sleep(30)
    health: dict = {}
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"{host}/health", timeout=20) as resp:
                health = json.loads(resp.read())
            if health.get("rag_index_ready"):
                break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        time.sleep(10)
    print(f"running at {host} (LLM {health.get('llm')}, Langfuse {health.get('langfuse', {}).get('enabled')})")
    return host


# ---- Vercel -------------------------------------------------------------------------------
def vercel(cfg: dict[str, str], api_url: str) -> str:
    step("Vercel: the UI")
    token, web = cfg["VERCEL_TOKEN"], ROOT / "web"
    npx = shutil.which("npx") or "npx"

    def run(*args: str) -> str:
        out = subprocess.run([npx, "--yes", "vercel", *args, "--token", token], cwd=web, capture_output=True,
                             text=True, encoding="utf-8", errors="replace")
        if out.returncode:
            raise SystemExit(f"vercel {args[0]} failed:\n{out.stderr[-1500:]}")
        return out.stdout + out.stderr

    run("link", "--yes", "--project", VERCEL_PROJECT)
    log = run("deploy", "--prod", "--yes", "--build-env", f"NEXT_PUBLIC_API_URL={api_url}",
              "--env", f"NEXT_PUBLIC_API_URL={api_url}")
    aliases = re.findall(r"https://[a-z0-9-]+\.vercel\.app", log)
    url = next((a for a in aliases if a.startswith(f"https://{VERCEL_PROJECT}")), aliases[-1] if aliases else "")
    print(f"live at {url}")
    return url


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="neon,space,vercel")
    parts = set(parser.parse_args().only.split(","))
    cfg, app_env = read_env(DEPLOY_ENV), read_env(ROOT / ".env")
    need = {"neon": "NEON_API_KEY", "space": "HF_TOKEN", "vercel": "VERCEL_TOKEN"}
    missing = [need[p] for p in parts if need.get(p) and need[p] not in cfg]
    if missing:
        sys.exit(f"missing in .env.deploy: {', '.join(missing)}")

    database_url = neon(cfg) if "neon" in parts else read_env(DEPLOY_ENV).get("DATABASE_URL", "")
    cfg = read_env(DEPLOY_ENV)
    api_url = cfg.get("API_URL", "")
    if "space" in parts:
        if not database_url:
            sys.exit("no DATABASE_URL: run the neon part first")
        api_url = space(cfg, app_env, database_url)
        remember("API_URL", api_url)
    if "vercel" in parts:
        if not api_url:
            sys.exit("no API_URL: run the space part first")
        remember("WEB_URL", vercel(cfg, api_url))
    print("\ndone:", {k: v for k, v in read_env(DEPLOY_ENV).items() if k in ("API_URL", "WEB_URL")})


if __name__ == "__main__":
    main()
