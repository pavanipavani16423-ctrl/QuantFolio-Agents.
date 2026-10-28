# Deploying QuantFolio Agents (free tiers)

```text
Browser ──► Vercel (Next.js UI, web/)
               │  HTTPS: REST + live progress (SSE)
               ▼
            Hugging Face Space (Docker: FastAPI API + the risk and compliance A2A agents)
               │  TLS
               ▼
            Neon (Postgres)
```

| Part | Host and free plan | What the free plan means |
|---|---|---|
| UI | **Vercel Hobby** | free for personal, non-commercial projects |
| API + A2A agents | **Hugging Face Spaces, CPU basic** | 2 vCPU, 16 GB memory. The Space sleeps after 48 hours without visits; the next visit wakes it in about a minute |
| Database | **Neon Free** | 0.5 GB storage. The database suspends after 5 idle minutes and wakes on the next query (under a second) |

The database holds everything that must survive a restart:
* runs and their events;
* memory: reviews, preferences and notes;
* the research cache;
* the hash-chained audit log;
* the LangGraph checkpoints, so a plan waiting for approval survives a restart;
* the paper-broker ledger;
* the clients you add.

The search models and the RAG index are built into the Docker image, so the Space needs no disk
of its own.

## One command

1. Create three tokens and put them in `.env.deploy` at the repository root. The file is
   git-ignored; never commit it.

   ```bash
   HF_TOKEN=hf_...          # huggingface.co → Settings → Access Tokens → New token, type "Write"
   NEON_API_KEY=napi_...    # console.neon.tech → Account settings → API keys
   VERCEL_TOKEN=...         # vercel.com → Account Settings → Tokens
   ```

   The app's own secrets (`GROQ_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) are read
   from `.env`.

2. Run:

   ```bash
   uv run --with huggingface_hub python scripts/deploy.py
   ```

What it does, step by step. Running it again updates the same projects.

1. **Neon:**
   * creates (or reuses) the project `quantfolio` in Singapore;
   * saves its connection string to `.env.deploy`.
2. **Hugging Face:**
   * creates (or reuses) the Docker Space `<your-account>/quantfolio-api`;
   * stores the secrets (Neon URL, Groq and Langfuse keys, a generated approval key) as Space
     secrets;
   * sets the variables (CORS for the Vercel address, the public URL);
   * uploads the backend files from git, then waits for the build (about 10 minutes the first
     time) and for `/health`.
3. **Vercel:**
   * creates (or reuses) the project `quantfolio-agents` from `web/`;
   * sets `NEXT_PUBLIC_API_URL` to the Space address;
   * deploys to production and prints the address.

Each part can be run alone: `--only neon`, `--only space` or `--only vercel`.

## Checking it works

* `https://<your-account>-quantfolio-api.hf.space/health` shows `"status":"ok"`, the LLM,
  Langfuse on and `"rag_index_ready":true`.
* Open the Vercel address. The header says **Ready · groq**.
* Run the GreenLeaf example. The decision box appears in about 20–40 seconds.
* Approve the plan, then restart the Space (Settings → Restart). The run, its audit trail and
  the new account value are still there, because they live in Neon.

## Security notes

* No secret is in the repository:
  * the tokens are in `.env.deploy` (git-ignored);
  * the app secrets are Space secrets, which the Space's public page does not show;
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

## Alternative: Render instead of Hugging Face

`render.yaml` describes the same backend as a Render web service. Render's free plan (0.1 CPU,
512 MB, sleeps after 15 idle minutes) is very small for this app. On it, a plan takes minutes, so
the file asks for the Standard plan (paid). Steps:
1. **New > Blueprint**, then pick the repository;
2. fill in `DATABASE_URL` and the keys;
3. set `CORS_ORIGINS` to the Vercel address.

## Running the same thing locally

* **With Docker:** `docker compose up --build`. It starts Postgres in place of Neon, the API, the
  two A2A agents as separate services, and the UI on http://localhost:3000. On Windows, Docker
  Desktop needs WSL 2 (`wsl --install` in an admin PowerShell, then restart).
* **Without Docker:** leave `DATABASE_URL` unset and everything uses SQLite files in `data/`.
* **The tests against Postgres, without Docker:**
  `uv run --with pgserver python scripts/test_postgres.py`.
