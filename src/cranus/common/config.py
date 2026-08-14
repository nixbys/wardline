"""Central application settings, loaded from environment variables / .env.

Every secret and tunable lives here so no module reaches into `os.environ`
directly. Validated eagerly at process startup (see api/main.py, worker/main.py,
cli.py) so misconfiguration fails fast instead of at first use.

`secrets_dir` makes this compatible with Docker/Kubernetes secret mounts out
of the box: pydantic-settings reads a file named after a field (e.g.
`/run/secrets/api_key_pepper`) as that field's value, taking priority over
plain environment variables. Point a secrets manager (Vault agent, K8s
Secret volume, `docker secret`) at `/run/secrets` instead of shipping real
credentials in a `.env` file on disk for any real deployment.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Only set secrets_dir when it actually exists: pydantic-settings just skips
# a missing directory with a warning, but there's no reason to pay even that
# cost (or risk a future pydantic-settings version tightening this to an
# error) in the common case of no secret-mount being present at all.
_SECRETS_DIR = "/run/secrets" if os.path.isdir("/run/secrets") else None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        secrets_dir=_SECRETS_DIR,
    )

    # --- App identity ---
    app_name: str = "cranus"
    environment: str = "development"

    # --- Postgres (app state + retrieval substrate) ---
    # Component fields are the source of truth so a single credential change
    # (e.g. postgres_password) stays consistent between what the app connects
    # with and what docker-compose.yml provisions the postgres container
    # with — previously these were two independently-hardcoded values that
    # could silently drift. Set database_url_override instead if you need a
    # connection string component fields can't express (e.g. a managed
    # Postgres with extra query params).
    postgres_user: str = "cranus"
    postgres_password: str = "cranus"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "cranus"
    database_url_override: str | None = None
    database_url_async_override: str | None = None

    @property
    def database_url(self) -> str:
        if self.database_url_override:
            return self.database_url_override
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_async(self) -> str:
        if self.database_url_async_override:
            return self.database_url_async_override
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

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

    # --- ASR (speech-to-text) for uploaded audio/video, via faster-whisper
    # (local, open-source, CTranslate2-backed -- no paid API, matching this
    # project's stance on embeddings/reranking). "tiny" is fast enough for
    # a lean single-node build; "small"/"medium"/"large-v3" trade speed for
    # accuracy on noisier recordings. See ingestion/extractors/audio.py.
    asr_model: str = "tiny"

    # --- OCR backend: local Tesseract (default, no external account needed)
    # or AWS Textract for higher accuracy on messier scans (see
    # ingestion/extractors/textract_ocr.py and "Scope reductions" in the
    # README). Textract needs real AWS credentials (boto3's standard chain:
    # env vars, ~/.aws/credentials, or an IAM role) -- not something this
    # repo can provide or live-test on its own.
    ocr_backend: str = "tesseract"  # "tesseract" | "textract"
    textract_region: str = "us-east-1"

    # --- Job dispatch: Postgres `SELECT ... FOR UPDATE SKIP LOCKED` (default,
    # zero extra infra -- see worker/jobs.py's own docstring on why this is
    # a real substitute for a Kafka consumer group's exactly-once-per-group
    # guarantee at this scale) or a real Kafka topic (see
    # worker/kafka_queue.py and "Scope reductions" in the README). The
    # IngestionJob row is still created either way -- it's this app's audit
    # trail / job-status API, not just a work queue.
    job_queue_backend: str = "postgres"  # "postgres" | "kafka"
    kafka_bootstrap_servers: str = "kafka:9092"
    kafka_ingestion_topic: str = "cranus-ingestion-jobs"

    # --- Lexical backend: Postgres tsvector (default, zero extra infra) or
    # real OpenSearch BM25 (see retrieval/opensearch_backend.py and
    # "Scope reductions" in the README). Switching doesn't touch anything
    # downstream of retrieval/lexical.py's lexical_search() -- fusion,
    # rerank, and the API only ever see RetrievedChunk rows either way.
    lexical_backend: str = "postgres"  # "postgres" | "opensearch"
    opensearch_url: str = "http://opensearch:9200"
    opensearch_index: str = "cranus-chunks"
    rerank_top_n: int = 12
    context_token_budget: int = 6000

    # --- Collection: crawler politeness ---
    crawler_user_agent: str = "cranus-research-bot/0.1 (+mailto:contact@example.com)"
    crawler_max_depth: int = 2
    crawler_max_pages_per_run: int = 200
    crawler_per_domain_delay_seconds: float = 1.0
    sec_edgar_user_agent: str = "cranus-research-bot contact@example.com"
    opencorporates_api_token: str | None = None

    # --- Governance / security ---
    api_key_pepper: str = Field(
        default="dev-only-insecure-pepper-change-me",
        description="Server-side secret mixed into API key hashing. MUST be overridden in any real deployment.",
    )
    kill_switch_enabled_default: bool = False
    rate_limit_query_per_minute: int = 30
    rate_limit_upload_per_minute: int = 10
    upload_max_bytes: int = 50 * 1024 * 1024  # 50 MiB

    # --- Auth mode: bearer API keys (default) or OIDC JWT bearer tokens ---
    # "api_key" is this project's own key system (governance/*, storage/models/governance.py).
    # "oidc" validates a JWT against a real identity provider's JWKS endpoint instead — set this
    # to move onto enterprise IAM (Okta/Auth0/Keycloak/Entra ID, anything OIDC-compliant) without
    # code changes. See api/oidc_auth.py.
    auth_mode: str = "api_key"  # "api_key" | "oidc"
    oidc_issuer: str | None = None
    oidc_jwks_url: str | None = None
    oidc_audience: str | None = None
    # Dotted path into the token claims. Keycloak (this project's live-tested
    # IdP) puts realm roles at `realm_access.roles`, not a flat top-level
    # claim -- found by live-testing against a real Keycloak instance rather
    # than assumed from the spec. Auth0/Okta typically use a flat namespaced
    # claim (e.g. "https://yourapp.example.com/roles"); override for those.
    oidc_role_claim: str = "realm_access.roles"
    # Maps a role string found in oidc_role_claim to this app's internal roles
    # (admin/analyst/viewer). Keys are matched case-insensitively.
    oidc_role_map: dict[str, str] = Field(
        default_factory=lambda: {"admin": "admin", "analyst": "analyst", "viewer": "viewer"}
    )

    # --- Agent mode guardrails ---
    agent_max_steps: int = 6
    agent_max_total_tokens: int = 20000

    # --- Entity resolution ---
    # Periodic Splink batch dedupe pass (graph/entity_resolution/splink_batch.py),
    # complementing the synchronous per-mention resolver used at ingestion time.
    entity_resolution_batch_enabled: bool = True
    entity_resolution_batch_interval_seconds: int = 21600  # 6 hours

    # --- Observability ---
    otel_console_export: bool = True
    otel_exporter_otlp_endpoint: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
