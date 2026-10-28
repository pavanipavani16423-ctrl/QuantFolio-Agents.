"""CI: run one whole plan in the backend image under the limits of Render's free plan.

    python3 scripts/check_free_plan.py quantfolio-api:ci

512 MB of memory without swap and 0.1 CPU, in the lean settings the deploy uses. Each phase is
published as a commit status ("free-plan"), which anyone can read without signing in, so the
result (time to ready, time for a plan, peak memory) is visible next to the commit.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "http://localhost:8000"
LIMITS = ["--memory", "512m", "--memory-swap", "512m", "--cpus", "0.1"]
LEAN = {"LLM_PROVIDER": "mock", "ONLINE_EVALUATION": "false", "RAG_RERANK_TOP": "10", "ONNX_THREADS": "1"}
REQUEST = {"client_id": "C-102", "request": "Rebalance GreenLeaf. What climate risks do NVIDIA and NextEra disclose?"}


def status(state: str, text: str) -> None:
    print(f"[{state}] {text}", flush=True)
    repo, sha, token = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_SHA"), os.environ.get("GH_TOKEN")
    if not (repo and sha and token):
        return
    body = json.dumps({"state": state, "context": "free-plan", "description": text[:139]}).encode()
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/statuses/{sha}", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
    try:
        urllib.request.urlopen(req, timeout=20).close()
    except urllib.error.URLError as exc:
        print(f"could not publish the status: {exc}", flush=True)


def get(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None,
                                 method="POST" if body else "GET", headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True).stdout.strip()


def last_error() -> str:
    logs = subprocess.run(["docker", "logs", "api"], capture_output=True, text=True)
    lines = [ln for ln in (logs.stdout + logs.stderr).splitlines() if ln.strip()]
    print("\n".join(lines[-40:]))
    bad = [ln for ln in lines if any(w in ln for w in ("Error", "error", "Killed", "Traceback", "failed"))]
    return (bad or lines or ["no output"])[-1][-100:]


def fail(text: str) -> None:
    oom = docker("inspect", "-f", "{{.State.OOMKilled}}", "api")
    status("failure", f"{text}; OOM killed {oom}; {last_error()}")
    sys.exit(1)


def main() -> None:
    image = sys.argv[1]
    env = [arg for k, v in LEAN.items() for arg in ("-e", f"{k}={v}")]
    status("pending", "starting the container at 512 MB, 0.1 CPU")
    out = subprocess.run(["docker", "run", "-d", "--name", "api", "-p", "8000:8000", *LIMITS, *env, image],
                         capture_output=True, text=True)
    if out.returncode:
        status("failure", f"docker run failed: {out.stderr.strip()[-110:]}")
        sys.exit(1)

    t0 = time.time()
    while True:
        try:
            if get("/health").get("rag_index_ready"):
                break
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
            pass
        if docker("inspect", "-f", "{{.State.Running}}", "api") != "true":
            fail(f"container stopped during start-up after {time.time() - t0:.0f}s")
        if time.time() - t0 > 900:
            fail("not ready after 900s")
        time.sleep(3)
    ready = time.time() - t0
    status("pending", f"ready in {ready:.0f}s; running a plan")

    run_id = get("/api/v1/runs", REQUEST)["id"]
    t1 = time.time()
    while True:
        try:
            doc = get(f"/api/v1/runs/{run_id}")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            if docker("inspect", "-f", "{{.State.Running}}", "api") != "true":
                fail(f"container stopped during the plan after {time.time() - t1:.0f}s")
            print(f"poll error: {exc}")
            doc = {"status": "running"}
        if doc["status"] in ("awaiting_approval", "failed", "blocked"):
            break
        if time.time() - t1 > 1200:
            fail("plan not done after 1200s")
        time.sleep(3)
    plan = time.time() - t1
    peak = int(docker("exec", "api", "cat", "/sys/fs/cgroup/memory.peak") or 0) // 2**20
    if doc["status"] != "awaiting_approval":
        fail(f"plan {doc['status']} after {plan:.0f}s: {(doc.get('error') or '')[:60]}")
    status("success", f"ready {ready:.0f}s, whole plan {plan:.0f}s, peak memory {peak} MiB of 512 (0.1 CPU)")


if __name__ == "__main__":
    main()
