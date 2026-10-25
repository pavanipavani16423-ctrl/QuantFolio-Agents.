"""All runtime configuration, read from environment variables or `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
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
    "groq": "qwen/qwen3.8-27b,openai/gpt-oss-120b",
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
    public_base_url: str = "http://localhost:8000"

    database_url: str = f"sqlite+aiosqlite:///{(ROOT / 'data' / 'quantfolio.db').as_posix()}"
    checkpoint_db: str = str(ROOT / "data" / "checkpoints.db")
    data_dir: Path = ROOT / "data"

    # LLM ("mock" = offline: deterministic rules, no model calls)
    llm_provider: Literal["mock", "groq", "openai", "anthropic", "ollama"] = "mock"
    llm_model: str | None = None
    llm_temperature: float = 0.0
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

    # Langfuse (tracing is off when the keys are missing)
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_environment: str = "development"

    # RAG
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rag_top_k: int = 6
    rag_candidates: int = 40
    rag_mode: Literal["bm25", "dense", "hybrid", "hybrid_rerank"] = "hybrid_rerank"

    # A2A: the risk and compliance agents are separate A2A services. By default the API
    # server hosts them under /a2a/*; point these at other hosts to run them separately.
    a2a_risk_url: str | None = None
    a2a_compliance_url: str | None = None
    a2a_timeout_seconds: float = 120.0

    # MCP
    mcp_transport: Literal["inprocess", "stdio"] = "inprocess"
    mcp_timeout_seconds: float = 300.0

    # Portfolio and quantum
    train_start: str = "2024-01-02"
    train_end: str = "2026-04-30"  # estimation window; everything after is out-of-sample
    qaoa_reps: int = 2
    qaoa_shots: int = 2048
    qaoa_maxiter: int = 60
    qaoa_mixer: Literal["xy", "x"] = "xy"
    qaoa_max_qubits: int = 20
    risk_free_rate: float = 0.04

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
