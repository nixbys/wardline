"""Central application settings, loaded from environment variables / .env.

Every secret and tunable lives here so no module reaches into `os.environ`
directly. Validated eagerly at process startup (see api/main.py, worker/main.py,
cli.py) so misconfiguration fails fast instead of at first use.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App identity ---
    app_name: str = "cranus"
    environment: str = "development"

    # --- Postgres (app state + retrieval substrate) ---
    database_url: str = "postgresql+psycopg://cranus:cranus@localhost:5432/cranus"
    database_url_async: str = "postgresql+asyncpg://cranus:cranus@localhost:5432/cranus"

    # --- Neo4j (knowledge graph) ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "cranus-dev-password"

    # --- Object store / bronze tier (S3-compatible, MinIO by default) ---
    blob_backend: str = "local"  # "local" | "s3"
    blob_local_root: str = "./data/bronze"
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "cranus"
    s3_secret_key: str = "cranus-dev-secret"
    s3_bucket: str = "cranus-bronze"
    s3_region: str = "us-east-1"

    # --- LLM (Anthropic / Claude) ---
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-4-8"
    llm_client_mode: str = "mock"  # "mock" | "live" — see query/llm_client.py

    # --- Embeddings / reranking (local, no paid API) ---
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # --- Chunking ---
    chunk_target_tokens: int = 500
    chunk_min_tokens: int = 300
    chunk_max_tokens: int = 800
    chunk_overlap_ratio: float = 0.15

    # --- Retrieval ---
    lexical_top_k: int = 50
    vector_top_k: int = 50
    rrf_k: int = 60
    rerank_top_n: int = 12
    context_token_budget: int = 6000

    # --- Collection: crawler politeness ---
    crawler_user_agent: str = "cranus-research-bot/0.1 (+mailto:contact@example.com)"
    crawler_max_depth: int = 2
    crawler_max_pages_per_run: int = 200
    crawler_per_domain_delay_seconds: float = 1.0
    sec_edgar_user_agent: str = "cranus-research-bot contact@example.com"

    # --- Governance / security ---
    api_key_pepper: str = Field(
        default="dev-only-insecure-pepper-change-me",
        description="Server-side secret mixed into API key hashing. MUST be overridden in any real deployment.",
    )
    kill_switch_enabled_default: bool = False
    rate_limit_query_per_minute: int = 30
    rate_limit_upload_per_minute: int = 10

    # --- Agent mode guardrails ---
    agent_max_steps: int = 6
    agent_max_total_tokens: int = 20000

    # --- Observability ---
    otel_console_export: bool = True
    otel_exporter_otlp_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
