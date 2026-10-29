# Deploying QuantFolio Agents (free tiers)

```text
Browser ──► Vercel (Next.js UI, web/)
               │  HTTPS: REST + live progress (SSE)
               ▼
            Render web service (Docker: FastAPI API + the risk and compliance A2A agents)
               │  TLS
               ▼
            Neon (Postgres)
```

| Part | Host and free plan | What the free plan means |
|---|---|---|
| UI | **Vercel Hobby** | free for personal, non-commercial projects |
| API + A2A agents | **Render Free** | 512 MB memory, 0.1 CPU. The service sleeps after 15 idle minutes; the next visit wakes it in about a minute |
| Database | **Neon Free** | 0.5 GB storage. The database suspends after 5 idle minutes and wakes on the next query (under a second) |

The database holds everything that must survive a restart:
* runs and their events;
* memory: reviews, preferences and notes;
* the research cache;
* the hash-chained audit log;
* the LangGraph checkpoints, so a plan waiting for approval survives a restart;
* the paper-broker ledger;
* the clients you add.

The search models and the RAG index are built into the Docker image, so the service needs no
disk of its own.

### Fitting in 512 MB

The free plan runs the app in a lean mode, set in `render.yaml` and by `scripts/deploy.py`:
* no background RAGAS judging (the deterministic checks still run on every plan);
* the int8 version of the reranker;
* lighter ONNX settings;
* one plan at a time (others wait in line).

The image also fixes glibc's allocator thresholds, so large buffers go back to the system when
they are freed. That one change took a plan's peak memory from 554 to 386 MiB.

CI checks this on every push: `scripts/check_free_plan.py` runs a whole plan in the image at
512 MB without swap and 0.1 CPU, and posts the result as the `free-plan` commit status. In two
runs: ready in 35–58 s, a whole plan in 41–74 s (mock model), peak about 430 MiB.

At 0.1 CPU the search steps are slow. Estimate for a real plan with Groq: about 1–2 minutes (41–74 s of
measured CPU work plus about 30 s of model calls), against about 40 s on a laptop. Search quality on the 78 labelled questions: 92.3% hit rate and MRR 0.902
in lean mode, against 94.9% and 0.901 with the full settings.

## One command

1. Create three tokens and put them in `.env.deploy` at the repository root. The file is
   git-ignored; never commit it.

   ```bash
   RENDER_API_KEY=rnd_...   # dashboard.render.com → Account Settings → API Keys
   NEON_API_KEY=napi_...    # console.neon.tech → Account settings → API keys
   VERCEL_TOKEN=...         # vercel.com → Account Settings → Tokens
   ```

   The app's own secrets (`GROQ_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) are read
   from `.env`.

2. Run:

   ```bash
   uv run python scripts/deploy.py
   ```

What it does, step by step. Running it again updates the same projects.

1. **Neon:**
   * creates (or reuses) the project `quantfolio` in Singapore;
   * saves its connection string to `.env.deploy`.
2. **Render:**
   * creates (or reuses) the free Docker web service `quantfolio-api` in Singapore, built from
     the GitHub repository, which redeploys on every push to `main`;
   * sets its environment: the Neon URL, the Groq and Langfuse keys, a generated approval key,
     CORS for the Vercel address, and the lean settings;
   * waits for the build (about 10 minutes the first time) and for `/health`.
3. **Vercel:**
   * creates (or reuses) the project `quantfolio-agents` from `web/`;
   * sets `NEXT_PUBLIC_API_URL` to the Render address;
   * deploys to production and prints the address.

Each part can be run alone: `--only neon`, `--only render` or `--only vercel`.

## Checking it works

* `https://<service>.onrender.com/health` (the address `deploy.py` prints; Render may add a suffix such as `-2qmc`) shows `"status":"ok"`, the LLM, Langfuse on and
  `"rag_index_ready":true`. After 15 idle minutes, the first request takes about a minute while
  the service wakes.
* Open the Vercel address. The header says **Ready · groq**.
* Run the GreenLeaf example. On the free plan, expect the decision box after about 1–2 minutes.
* Approve the plan, then restart the service (Manual Deploy → Restart). The run, its audit trail and
  the new account value are still there, because they live in Neon.

## Security notes

* No secret is in the repository:
  * the tokens are in `.env.deploy` (git-ignored);
  * the app secrets are Render environment variables, visible only to the account;
  * Vercel only holds the API address.
* The browser calls the API directly, so no API key is sent from the browser; it would be visible
  to anyone. The API is protected by:
  * CORS (only the Vercel address);
  * a per-address rate limit on new runs;
  * a request size limit;
  * the guardrails;
  * approvals bound to the exact orders.
* Trades are paper trades; the broker never touches real money.
* You can revoke the three deploy tokens after deploying. They are only needed to deploy again.

## Alternatives

* **Render from the dashboard:** **New > Blueprint** and pick the repository. `render.yaml` holds
  the same service and lean settings. Fill in `DATABASE_URL`, the keys and `CORS_ORIGINS`.
* **More speed:** a paid Render plan (Starter: 512 MB, 0.5 CPU; Standard: 2 GB, 1 CPU). There you
  can drop the lean settings, so background judging and the full reranker are back.
* **Hugging Face Spaces:** `--only space` deploys the same image as a Docker Space (2 vCPU,
  16 GB). Docker Spaces need a PRO account since 2026.

## Running the same thing locally

* **With Docker:** `docker compose up --build`. It starts Postgres in place of Neon, the API, the
  two A2A agents as separate services, and the UI on http://localhost:3000. On Windows, Docker
  Desktop needs WSL 2 (`wsl --install` in an admin PowerShell, then restart).
* **Without Docker:** leave `DATABASE_URL` unset and everything uses SQLite files in `data/`.
* **The tests against Postgres, without Docker:**
  `uv run --with pgserver python scripts/test_postgres.py`.
