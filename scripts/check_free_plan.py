"""CI: run one whole plan in the backend image under the limits of Render's free plan.

    python3 scripts/check_free_plan.py quantfolio-api:ci

First without a memory limit (to measure the true peak), then at 512 MB without swap and 0.1 CPU,
in the lean settings the deploy uses. Each phase is published as a commit status ("free-plan"),
which anyone can read without signing in.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = "http://localhost:8000"
FREE_PLAN = ["--memory", "512m", "--memory-swap", "512m", "--cpus", "0.1"]
LEAN = {"LLM_PROVIDER": "mock", "ONLINE_EVALUATION": "false", "RAG_RERANK_TOP": "10", "ONNX_THREADS": "1",
        "ONNX_MEMORY_ARENA": "false", "ONNX_GRAPH_OPTIMIZATION": "extended",
        "RERANKER_MODEL": "Xenova/ms-marco-MiniLM-L-6-v2-int8", "MAX_CONCURRENT_RUNS": "1"}
# Meera Iyer: the largest search (10 of 20 stocks, 184,756 combinations)
REQUEST = {"client_id": "C-101", "request": "Rebalance Meera's portfolio. What risks do Johnson & Johnson and Coca-Cola report?"}


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


def call(path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None,
                                 method="POST" if body else "GET", headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def docker(*args: str) -> str:
    return subprocess.run(["docker", *args], capture_output=True, text=True).stdout.strip()


def running() -> bool:
    return docker("inspect", "-f", "{{.State.Running}}", "api") == "true"


def failure(text: str) -> None:
    logs = subprocess.run(["docker", "logs", "api"], capture_output=True, text=True)
    lines = [ln for ln in (logs.stdout + logs.stderr).splitlines() if ln.strip()]
    print("\n".join(lines[-40:]))
    bad = [ln for ln in lines if any(w in ln for w in ("Error", "Killed", "Traceback", "failed"))]
    oom = docker("inspect", "-f", "{{.State.OOMKilled}}", "api")
    status("failure", f"{text}; OOM killed {oom}; {(bad or lines or ['no output'])[-1][-80:]}")
    sys.exit(1)


def memory_stat() -> dict[str, int]:
    """The container's anonymous memory (what the process allocates) and page cache, in MiB."""
    raw = docker("exec", "api", "cat", "/sys/fs/cgroup/memory.stat")
    stat = dict((ln.split()[0], int(ln.split()[1])) for ln in raw.splitlines() if len(ln.split()) == 2)
    return {"anon": stat.get("anon", 0) // 2**20, "file": stat.get("file", 0) // 2**20}


ANON_PEAK = {"ready": 0, "plan": 0}
BY_STEP: dict[str, int] = {}  # highest anonymous memory seen while each step was running


# allocator settings compared without a memory limit; the lowest peak then runs at the free plan's
FIXED_MALLOC = {"MALLOC_MMAP_THRESHOLD_": "131072", "MALLOC_TRIM_THRESHOLD_": "131072"}  # big buffers go back to the OS
ONE_TOKENIZER_THREAD = {"TOKENIZERS_PARALLELISM": "false", "RAYON_NUM_THREADS": "1"}  # not a thread per host core
VARIANTS = {
    "base": {},
    "malloc": FIXED_MALLOC,
    "tokenizer": ONE_TOKENIZER_THREAD,
    "both": {**FIXED_MALLOC, **ONE_TOKENIZER_THREAD},
}


def run_plan(image: str, limits: list[str], label: str, extra: dict[str, str] | None = None) -> tuple[float, float, int]:
    """Start the container, wait until ready, run one plan; (ready s, plan s, peak MiB)."""
    subprocess.run(["docker", "rm", "-f", "api"], capture_output=True)
    BY_STEP.clear()
    env = [arg for k, v in {**LEAN, **(extra or {})}.items() for arg in ("-e", f"{k}={v}")]
    out = subprocess.run(["docker", "run", "-d", "--name", "api", "-p", "8000:8000", *limits, *env, image],
                         capture_output=True, text=True)
    if out.returncode:
        status("failure", f"{label}: docker run failed: {out.stderr.strip()[-100:]}")
        sys.exit(1)
    t0 = time.time()
    while True:
        try:
            if call("/health").get("rag_index_ready"):
                break
        except (urllib.error.URLError, ConnectionError, TimeoutError, json.JSONDecodeError):
            pass
        if not running():
            failure(f"{label}: stopped during start-up after {time.time() - t0:.0f}s")
        if time.time() - t0 > 900:
            failure(f"{label}: not ready after 900s")
        time.sleep(3)
    ready = time.time() - t0
    ANON_PEAK["ready"] = memory_stat()["anon"]
    ANON_PEAK["plan"] = ANON_PEAK["ready"]
    run_id = call("/api/v1/runs", REQUEST)["id"]
    t1 = time.time()
    while True:
        try:
            doc = call(f"/api/v1/runs/{run_id}")
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if not running():
                failure(f"{label}: stopped during the plan after {time.time() - t1:.0f}s")
            doc = {"status": "running"}
        try:
            anon = memory_stat()["anon"]
            ANON_PEAK["plan"] = max(ANON_PEAK["plan"], anon)
            for key, step in doc.get("steps", {}).items():
                if step.get("status") == "running":
                    BY_STEP[key] = max(BY_STEP.get(key, 0), anon)
        except (ValueError, IndexError):
            pass
        if doc["status"] in ("awaiting_approval", "failed", "blocked"):
            break
        if time.time() - t1 > 1200:
            failure(f"{label}: plan not done after 1200s")
        time.sleep(0.5)
    plan = time.time() - t1
    if doc["status"] != "awaiting_approval":
        failure(f"{label}: plan {doc['status']} after {plan:.0f}s: {(doc.get('error') or '')[:50]}")
    peak = int(docker("exec", "api", "cat", "/sys/fs/cgroup/memory.peak") or 0) // 2**20
    return ready, plan, peak


def main() -> None:
    image = sys.argv[1]
    status("pending", f"comparing {len(VARIANTS)} allocator settings without a memory limit")
    peaks = {}
    for name, extra in VARIANTS.items():
        _, plan_s, _ = run_plan(image, ["--cpus", "1"], name, extra)
        profile = docker("exec", "api", "python", "scripts/profile_memory.py").splitlines()
        steps = " ".join(f"{k}={v}" for k, v in sorted(BY_STEP.items(), key=lambda kv: -kv[1])[:3])
        peaks[name] = ANON_PEAK["plan"]
        status("pending", f"{name}: anon ready {ANON_PEAK['ready']}, plan peak {ANON_PEAK['plan']} MiB ({steps}); "
                          f"search: {(profile[-1] if profile else 'no profile')[-60:]}")
        time.sleep(1)
    best = min(peaks, key=peaks.get)
    ready, plan, peak = run_plan(image, FREE_PLAN, f"free plan ({best})", VARIANTS[best])
    status("success", f"512 MB/0.1 CPU with {best}: ready {ready:.0f}s, plan {plan:.0f}s, anon peak "
                      f"{ANON_PEAK['plan']} MiB; unlimited peaks " + ", ".join(f"{k} {v}" for k, v in peaks.items()))


if __name__ == "__main__":
    main()
