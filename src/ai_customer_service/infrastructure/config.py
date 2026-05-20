from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_file_encoding="utf-8")

    # --- LLM ---
    LLM_PROVIDER: Literal["openai", "openai_compat", "anthropic", "ollama"] = "openai_compat"
    LLM_MODEL: str = "deepseek-chat"
    LLM_API_KEY: str = ""        # For openai / openai_compat providers
    LLM_BASE_URL: str = ""       # Custom endpoint for openai_compat (e.g. DeepSeek, vLLM)
    LLM_TEMPERATURE: float = 0.0
    ANTHROPIC_API_KEY: str = ""  # For anthropic provider
    OLLAMA_BASE_URL: str = "http://localhost:11434"  # For ollama provider

    # --- Embedding ---
    EMBEDDING_PROVIDER: str = "minimax"  # "local" | "minimax" | "openai"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_API_KEY: str = ""  # Falls back to LLM_API_KEY when empty
    EMBEDDING_BASE_URL: str = "" # Falls back to LLM_BASE_URL when empty

    # --- PostgreSQL ---
    POSTGRES_URL: str = "postgresql+asyncpg://csuser:cspass@localhost:5432/customer_service"
    POSTGRES_POOL_SIZE: int = Field(default=10, ge=1, le=50)

    # Sync URL for langgraph-checkpoint-postgres (uses psycopg3, not asyncpg)
    @property
    def POSTGRES_SYNC_URL(self) -> str:
        return self.POSTGRES_URL.replace("postgresql+asyncpg://", "postgresql://")

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Langfuse ---
    LANGFUSE_ENABLED: bool = True
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # --- RAG ---
    RERANKER_ENABLED: bool = False
    RERANKER_MODEL: str = "BAAI/bge-reranker-base"
    RETRIEVAL_K: int = Field(default=5, ge=1, le=20)

    # --- Auth / JWT ---
    # Leave JWT_SECRET empty to run in open/guest mode (no token required).
    # Set JWT_SECRET (HS256) or JWT_JWKS_URL (RS256/ES256 via JWKS endpoint)
    # to enforce authentication.
    #
    # HS256 (simple, symmetric — for self-hosted single-service deployments):
    #   JWT_SECRET=my-very-long-secret
    #
    # RS256 / ES256 via JWKS (recommended for third-party IdPs like Auth0,
    #   Keycloak, Cognito, Authing, Casdoor, etc.):
    #   JWT_JWKS_URL=https://your-idp.example.com/.well-known/jwks.json
    #   JWT_ALGORITHM=RS256
    #
    JWT_SECRET: str = ""                        # HS256 shared secret
    JWT_ALGORITHM: str = "HS256"               # HS256 | RS256 | ES256
    JWT_JWKS_URL: str = ""                     # JWKS endpoint (RS256/ES256)
    JWT_ISSUER: str = ""                       # iss claim to verify (optional)
    JWT_AUDIENCE: str = ""                     # aud claim to verify (optional)
    JWT_REQUIRED: bool = False                 # False = guest fallback allowed

    # --- App ---
    APP_ENV: Literal["development", "staging", "production"] = "development"
    LOG_LEVEL: str = "INFO"

    # Daily digest scheduler
    DIGEST_HOUR: int = Field(default=8, ge=0, le=23, description="Hour (0-23) to generate daily digest (server local time)")
    DIGEST_WEBHOOK_URL: str | None = Field(default=None, description="Optional webhook URL to POST digest JSON to")

    # --- Language ---
    # 客服系统默认回复语言。当无法检测客户语言时使用此默认值。
    # 可通过后台 API 动态覆盖：PUT /api/admin/rules/default_language {"value": "en"}
    # 常用值：zh-CN（简体中文）、en（英语）、ja（日语）、ko（韩语）
    DEFAULT_LANGUAGE: str = "zh-CN"

    # --- Business Profile ---
    # Which business profile to load from the business_profiles table.
    # Change this (or set BUSINESS_ID env var) to switch the active business
    # without changing any code — just ensure the profile + intents are seeded.
    BUSINESS_ID: str = "wedding_dress"

    # ── Data Sources ──────────────────────────────────────────────────────────
    # Each source has a TYPE (internal_db | rest_api) and optional connection
    # fields.  Fields only need to be set when TYPE=rest_api.
    #
    # AUTH options: none | api_key | bearer | oauth2 | basic
    #
    # Order data source (OMS / ERP integration)
    ORDER_SOURCE_TYPE: Literal["internal_db", "rest_api"] = "internal_db"
    ORDER_SOURCE_URL: str = ""                    # required when TYPE=rest_api
    ORDER_SOURCE_AUTH: str = "none"
    ORDER_SOURCE_API_KEY: str = ""
    ORDER_SOURCE_API_KEY_HEADER: str = "X-API-Key"
    ORDER_SOURCE_BEARER_TOKEN: str = ""
    ORDER_SOURCE_OAUTH2_TOKEN_URL: str = ""
    ORDER_SOURCE_OAUTH2_CLIENT_ID: str = ""
    ORDER_SOURCE_OAUTH2_CLIENT_SECRET: str = ""
    ORDER_SOURCE_OAUTH2_SCOPE: str = ""
    ORDER_SOURCE_BASIC_USER: str = ""
    ORDER_SOURCE_BASIC_PASS: str = ""
    ORDER_SOURCE_TIMEOUT: float = 30.0

    # Product catalog data source (PIM / e-commerce platform sync)
    PRODUCT_SOURCE_TYPE: Literal["internal_db", "rest_api"] = "internal_db"
    PRODUCT_SOURCE_URL: str = ""
    PRODUCT_SOURCE_AUTH: str = "none"
    PRODUCT_SOURCE_API_KEY: str = ""
    PRODUCT_SOURCE_API_KEY_HEADER: str = "X-API-Key"
    PRODUCT_SOURCE_BEARER_TOKEN: str = ""
    PRODUCT_SOURCE_OAUTH2_TOKEN_URL: str = ""
    PRODUCT_SOURCE_OAUTH2_CLIENT_ID: str = ""
    PRODUCT_SOURCE_OAUTH2_CLIENT_SECRET: str = ""
    PRODUCT_SOURCE_OAUTH2_SCOPE: str = ""
    PRODUCT_SOURCE_BASIC_USER: str = ""
    PRODUCT_SOURCE_BASIC_PASS: str = ""
    PRODUCT_SOURCE_TIMEOUT: float = 60.0

    # FAQ / knowledge base data source (CMS / Zendesk / Notion sync)
    FAQ_SOURCE_TYPE: Literal["internal_db", "rest_api"] = "internal_db"
    FAQ_SOURCE_URL: str = ""
    FAQ_SOURCE_AUTH: str = "none"
    FAQ_SOURCE_API_KEY: str = ""
    FAQ_SOURCE_API_KEY_HEADER: str = "X-API-Key"
    FAQ_SOURCE_BEARER_TOKEN: str = ""
    FAQ_SOURCE_OAUTH2_TOKEN_URL: str = ""
    FAQ_SOURCE_OAUTH2_CLIENT_ID: str = ""
    FAQ_SOURCE_OAUTH2_CLIENT_SECRET: str = ""
    FAQ_SOURCE_OAUTH2_SCOPE: str = ""
    FAQ_SOURCE_BASIC_USER: str = ""
    FAQ_SOURCE_BASIC_PASS: str = ""
    FAQ_SOURCE_TIMEOUT: float = 60.0

    # ------------------------------------------------------------------
    # Resolved connection kwargs — all provider-specific logic lives here
    # so LLMFactory stays a thin dispatcher with no conditional branching.
    # ------------------------------------------------------------------

    def llm_kwargs(self) -> dict[str, Any]:
        """Return the exact keyword arguments to pass to the LangChain chat model."""
        kwargs: dict[str, Any] = {
            "model": self.LLM_MODEL,
            "temperature": self.LLM_TEMPERATURE,
        }
        if self.LLM_PROVIDER in ("openai", "openai_compat"):
            kwargs["api_key"] = self.LLM_API_KEY or "placeholder"
            if self.LLM_BASE_URL:
                kwargs["base_url"] = self.LLM_BASE_URL
        elif self.LLM_PROVIDER == "anthropic":
            kwargs["api_key"] = self.ANTHROPIC_API_KEY
        elif self.LLM_PROVIDER == "ollama":
            kwargs["base_url"] = self.OLLAMA_BASE_URL
        return kwargs

    def embedding_kwargs(self) -> dict[str, Any]:
        """Return the exact keyword arguments to pass to the embedding client."""
        return {
            "model": self.EMBEDDING_MODEL,
            "api_key": self.EMBEDDING_API_KEY or self.LLM_API_KEY or "placeholder",
            "base_url": self.EMBEDDING_BASE_URL or self.LLM_BASE_URL or None,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
