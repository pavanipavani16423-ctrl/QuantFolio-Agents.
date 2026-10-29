# Backend image: the API and the hosted A2A agents (risk, compliance).
#
# The embedding and reranker models are downloaded at build time and the RAG index loads from
# data/index (committed), so a container starts in seconds and needs no disk of its own: state
# lives in DATABASE_URL (Neon Postgres in the cloud, a SQLite file when unset).
#
#   docker build -t quantfolio-api .
#   docker run -p 8000:8000 --env-file .env quantfolio-api

FROM python:3.11-slim AS build
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
RUN pip install --no-cache-dir uv==0.11.28
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY data ./data
RUN .venv/bin/python -c "from app.rag.index import get_index; i = get_index(); print(len(i.chunks), 'chunks ready')"
# the int8 reranker of the free-plan settings, so a small server does not download it at start-up
RUN RERANKER_MODEL=Xenova/ms-marco-MiniLM-L-6-v2-int8 .venv/bin/python -c "from app.rag.index import _models; _models()"

FROM python:3.11-slim
# MALLOC_ARENA_MAX: glibc keeps a memory pool per thread by default, which inflates a Python
# server's memory with every worker thread; two pools are plenty.
# *_NUM_THREADS=1: numpy's BLAS starts a thread (with its own buffer) per host core on the first
# matrix product; the matrices here are small, and a 0.1-CPU slice of a many-core host would get
# dozens of threads.
# MALLOC_MMAP/TRIM_THRESHOLD_: fixed, so large buffers (ONNX tensors, numpy arrays) are mapped and
# returned to the OS when freed. By default glibc raises the threshold after the first such free
# and keeps later ones in its heap. Measured in CI, the peak of a whole plan went from 554 to
# 386 MiB; with one tokenizer thread, 366 MiB.
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" PORT=8000 ENVIRONMENT=production \
    MALLOC_ARENA_MAX=2 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
    MALLOC_MMAP_THRESHOLD_=131072 MALLOC_TRIM_THRESHOLD_=131072 TOKENIZERS_PARALLELISM=false RAYON_NUM_THREADS=1
WORKDIR /app
RUN useradd --create-home --uid 1000 app  # uid 1000: what Hugging Face Spaces runs containers as
COPY --from=build /app/.venv ./.venv
COPY --from=build --chown=app:app /app/data ./data
COPY app ./app
COPY scripts ./scripts
COPY experiments/results ./experiments/results
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/health', timeout=4)"
# Render (and most hosts) put a proxy in front: trust its X-Forwarded-For so the rate limiter
# sees the real client address, not the proxy's
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\" --proxy-headers --forwarded-allow-ips='*'"]
