"""All runtime configuration, read from environment variables or `.env`."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]

# Groq (October 2026): gpt-oss-120b is the strongest model on the free tier with reliable tool
# calling / structured output. The judge uses a different model on purpose: Groq rate limits
# are per model, so agents and judge do not compete for the same token budget.
DEFAULT_LLM_MODELS = {
    "groq": "openai/gpt-oss-120b",
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-haiku-5-5",
    "ollama": "qwen2.5:7b",
    "mock": "rule-based",
}

DEFAULT_JUDGE_MODELS = {
    "groq": "qwen/qwen3.8-27b",
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-haiku-5-5",
    "ollama": "qwen2.5:7b",
    "mock": "none",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "QuantFolio Agents"
    environment: str = "development"
    log_level: str = "INFO"
    api_key: SecretStr | None = None
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    cors_origin_regex: str | None = None  # e.g. https://quantfolio-.*\.vercel\.app for Vercel previews
    # where the hosted A2A agents are reachable; Render sets RENDER_EXTERNAL_URL itself
    public_base_url: str = Field(default_factory=lambda: os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000"))

    database_url: str = f"sqlite+aiosqlite:///{(ROOT / 'data' / 'quantfolio.db').as_posix()}"
    checkpoint_db: str = str(ROOT / "data" / "checkpoints.db")
    data_dir: Path = ROOT / "data"
    clients_dir: Path = ROOT / "data" / "clients"  # clients the advisor adds in the UI (git-ignored)

    # LLM ("mock" = offline: deterministic rules, no model calls)
    llm_provider: Literal["mock", "groq", "openai", "anthropic", "ollama"] = "mock"
    llm_model: str | None = None
    llm_temperature: float = 0.0
    # how structured output is requested first: json_schema (provider-enforced schema, Groq and
    # OpenAI) or function_calling (a tool call); json_mode is the fallback either way
    llm_structured_method: Literal["json_schema", "function_calling"] = "function_calling"
    llm_timeout_seconds: float = 120.0
    llm_max_retries: int = 6  # the SDK waits for the rate-limit window (Retry-After) between tries
    llm_reasoning_effort: str = "low"  # for reasoning models (gpt-oss): fewer tokens, lower latency
    groq_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434"

    # RAGAS judge (defaults to the same provider as the agents)
    judge_provider: Literal["mock", "groq", "openai", "anthropic", "ollama"] | None = None
    judge_model: str | None = None
    online_evaluation: bool = True
    # share of runs judged by RAGAS in the background (the deterministic checks run on every run);
    # chosen from the run id, so the same run is always in or out
    online_evaluation_sample_rate: float = 1.0

    # Langfuse (tracing is off when the keys are missing)
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "development"

    # RAG. Chosen with scripts/tune_rag.py (experiments/results/rag_tuning_*.json): 1100-char chunks
    # beat 500/800; bge-base and the query prefix did not improve the reranked result; MiniLM-L-12
    # found one more of 78 questions but ranked worse (MRR) at twice the latency, so L-6 stays.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    embedding_query_prefix: bool = False  # the model's retrieval instruction on queries
    chunk_target_chars: int = 1100
    chunk_max_chars: int = 1600
    rag_top_k: int = 6
    rag_candidates: int = 40
    rag_rerank_top: int = 20
    onnx_threads: int | None = None  # threads per ONNX model (embedding, reranker); None = one per core
    onnx_memory_arena: bool = True  # False: ONNX frees inference buffers (lower peak memory, a little slower)
    # "extended" skips the last ONNX optimisations, which turn the int8 embedding model back into float
    # copies: 73 MB instead of 114 MB of memory
    onnx_graph_optimization: Literal["basic", "extended", "all"] = "all"
    max_concurrent_runs: int = 2  # plans executing at once; more wait in line (1 on a 512 MB server)
    rerank_batch_size: int = 4  # passages scored per reranker call (1 = lowest peak memory)
    prompt_passage_chars: int = 1600  # passage text given to the research model and the judge (whole chunks)
    rag_mode: Literal["bm25", "dense", "hybrid", "hybrid_rerank"] = "hybrid_rerank"

    # A2A: the risk and compliance agents are separate A2A services. By default the API
    # server hosts them under /a2a/*; point these at other hosts to run them separately.
    a2a_risk_url: str | None = None
    a2a_compliance_url: str | None = None
    a2a_timeout_seconds: float = 120.0

    # MCP
    mcp_transport: Literal["inprocess", "stdio"] = "inprocess"
    mcp_timeout_seconds: float = 300.0

    # Portfolio
    train_start: str = "2024-01-02"
    train_end: str = "2026-04-30"  # estimation window; everything after is out-of-sample
    risk_free_rate: float = 0.04

    # Guardrails and security
    guardrails_enabled: bool = True
    injection_block_threshold: float = 1.0  # signal score at or above which a request is stopped
    # second stage of the injection detector (embedding similarity to attack intents); set by
    # scripts/eval_guardrails.py (highest benign similarity + 0.02, bge-small); None switches it off
    semantic_injection_threshold: float | None = 0.706
    citation_gate_enabled: bool = True
    # cross-encoder score (MiniLM-L-6): 5th percentile of correctly cited claims, from
    # scripts/calibrate_citations.py; accepts 95% of them, rejects 94% of same-company wrong-source claims
    citation_support_threshold: float = 1.24
    approval_secret: SecretStr | None = None  # signs approval tokens; a local file is used if unset
    approval_ttl_seconds: int = 900
    rate_limit_runs: int = 12  # new runs per client address per rate_limit_window_seconds
    rate_limit_window_seconds: int = 600
    max_tool_calls_per_run: int = 120
    max_order_fraction: float = 0.35  # no single order above this share of the account value
    max_turnover: float = 2.0  # buys + sells as a multiple of the account value

    # Memory
    memory_episodes_recalled: int = 3
    memory_notes_recalled: int = 5
    research_cache_enabled: bool = True
    research_cache_similarity: float = 0.95
    research_cache_ttl_hours: float = 168.0

    run_timeout_seconds: float = 900.0
    max_body_bytes: int = 256_000

    @property
    def resolved_llm_model(self) -> str:
        return self.llm_model or DEFAULT_LLM_MODELS[self.llm_provider]

    @property
    def resolved_judge_provider(self) -> str:
        return self.judge_provider or self.llm_provider

    @property
    def resolved_judge_model(self) -> str:
        return self.judge_model or DEFAULT_JUDGE_MODELS[self.resolved_judge_provider]

    def api_key_for(self, provider: str) -> str | None:
        secret = {
            "groq": self.groq_api_key,
            "openai": self.openai_api_key,
            "anthropic": self.anthropic_api_key,
        }.get(provider)
        return secret.get_secret_value() if secret else None

    def provider_ready(self, provider: str) -> bool:
        if provider == "mock":
            return False
        if provider == "ollama":
            return True
        return bool(self.api_key_for(provider))

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
