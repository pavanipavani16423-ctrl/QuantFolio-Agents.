"""LangChain chat-model factory for the configured provider."""

from typing import Any

from app.config import Settings


class LLMConfigError(Exception):
    pass


def create_chat_model(settings: Settings, provider: str, model: str, max_tokens: int = 2048) -> Any:
    if provider == "mock":
        raise LLMConfigError("mock provider has no model")
    if not settings.provider_ready(provider):
        raise LLMConfigError(f"no API key configured for LLM provider {provider!r}")
    common = {"temperature": settings.llm_temperature}
    try:
        match provider:
            case "groq":
                from langchain_groq import ChatGroq

                extra = {}
                if model.startswith("openai/gpt-oss"):
                    extra["reasoning_effort"] = settings.llm_reasoning_effort
                elif model.startswith("qwen/qwen3"):
                    # no hidden "thinking" tokens: they count against the free tier's small
                    # output-tokens-per-minute limit and add nothing to a structured verdict
                    extra["reasoning_effort"] = "none"
                return ChatGroq(model=model, api_key=settings.api_key_for("groq"),
                                timeout=settings.llm_timeout_seconds, max_tokens=max_tokens,
                                max_retries=settings.llm_max_retries, **extra, **common)
            case "openai":
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(model=model, api_key=settings.api_key_for("openai"),
                                  timeout=settings.llm_timeout_seconds, max_tokens=max_tokens,
                                  max_retries=settings.llm_max_retries, **common)
            case "anthropic":
                from langchain_anthropic import ChatAnthropic

                return ChatAnthropic(model=model, api_key=settings.api_key_for("anthropic"),
                                     timeout=settings.llm_timeout_seconds, max_tokens=max_tokens,
                                     **common)
            case "ollama":
                from langchain_ollama import ChatOllama

                return ChatOllama(model=model, base_url=settings.ollama_base_url, **common)
    except ImportError as exc:
        raise LLMConfigError(f"provider {provider!r} needs its LangChain package") from exc
    raise LLMConfigError(f"unknown provider {provider!r}")
