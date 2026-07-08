"""initial schema: extensions, tsvector helper, all core tables, audit-log lockdown

Revision ID: 0001
Revises:
Create Date: 2026-07-07

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 384  # keep in sync with common/config.py Settings.embedding_dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # to_tsvector(regconfig, text) is STABLE not IMMUTABLE (it depends on the
    # text-search configuration catalog), so Postgres refuses it directly in a
    # GENERATED ALWAYS AS column. Wrapping it and asserting IMMUTABLE is the
    # standard, widely-used pattern for this — we pin the 'english' config, so
    # for a fixed Postgres install its result really is a pure function of the
    # input text.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cranus_to_tsvector(input_text text)
        RETURNS tsvector
        LANGUAGE sql
        IMMUTABLE
        PARALLEL SAFE
        AS $$
            SELECT to_tsvector('pg_catalog.english', coalesce(input_text, ''))
        $$;
        """
    )

    op.create_table(
        "sources",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("default_license", sa.String(128), nullable=False),
        sa.Column("config_schema", JSONB, nullable=False, server_default="{}"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="viewer"),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.String(256), nullable=False),
        sa.Column("lookup_hash", sa.String(64), nullable=False),
        sa.Column("scopes", JSONB, nullable=False, server_default="[]"),
        sa.Column("revoked", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_api_keys_lookup_hash", "api_keys", ["lookup_hash"])

    op.create_table(
        "documents",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("uri", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("license", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("lang", sa.String(16), nullable=False, server_default="en"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("quarantine_reason", sa.Text, nullable=True),
        sa.Column("source_connector", sa.String(64), nullable=False),
        sa.Column("blob_key", sa.Text, nullable=True),
        sa.Column("extra", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_documents_content_hash", "documents", ["content_hash"])
    op.create_index("ix_documents_source_connector", "documents", ["source_connector"])
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "doc_id", sa.String(64), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("char_start", sa.Integer, nullable=False),
        sa.Column("char_end", sa.Integer, nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
        sa.Column("embedding_model", sa.String(128), nullable=True),
        sa.Column("pii_tags", JSONB, nullable=False, server_default="[]"),
        sa.Column(
            "tsv",
            TSVECTOR,
            sa.Computed("cranus_to_tsvector(text)", persisted=True),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_chunks_doc_id", "chunks", ["doc_id"])
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], postgresql_using="gin")
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )

    op.create_table(
        "entities",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("canonical_name", sa.String(512), nullable=False),
        sa.Column("aliases", JSONB, nullable=False, server_default="[]"),
        sa.Column("attributes", JSONB, nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_entities_type", "entities", ["type"])
    op.create_index("ix_entities_canonical_name", "entities", ["canonical_name"])

    op.create_table(
        "edges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "from_entity_id", sa.String(64), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "to_entity_id", sa.String(64), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("evidence_chunk_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_edges_from_entity_id", "edges", ["from_entity_id"])
    op.create_index("ix_edges_to_entity_id", "edges", ["to_entity_id"])
    op.create_index("ix_edges_type", "edges", ["type"])

    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("chunk_id", sa.String(64), sa.ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("span_text", sa.String(512), nullable=False),
        sa.Column("span_start", sa.Integer, nullable=False),
        sa.Column("span_end", sa.Integer, nullable=False),
        sa.Column("ner_type", sa.String(64), nullable=False),
        sa.Column(
            "suggested_entity_id",
            sa.String(64),
            sa.ForeignKey("entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_entity_mentions_chunk_id", "entity_mentions", ["chunk_id"])

    op.create_table(
        "edge_candidates",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "from_mention_id",
            sa.String(64),
            sa.ForeignKey("entity_mentions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_mention_id",
            sa.String(64),
            sa.ForeignKey("entity_mentions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column(
            "evidence_chunk_id", sa.String(64), sa.ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_edge_candidates_status", "edge_candidates", ["status"])

    op.create_table(
        "entity_resolution_review",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "entity_a_id", sa.String(64), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "entity_b_id", sa.String(64), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(64), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_entity_resolution_review_status", "entity_resolution_review", ["status"])

    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "connector_name", sa.String(64), sa.ForeignKey("sources.name", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("params", JSONB, nullable=False, server_default="{}"),
        sa.Column("result", JSONB, nullable=False, server_default="{}"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(64), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_ingestion_jobs_status", "ingestion_jobs", ["status"])
    op.create_index("ix_ingestion_jobs_connector_name", "ingestion_jobs", ["connector_name"])

    op.create_table(
        "feedback",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_feedback_session_id", "feedback", ["session_id"])

    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", JSONB, nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_events_session_id", "audit_events", ["session_id"])
    op.create_index("ix_audit_events_created_at", "audit_events", ["created_at"])

    # --- Immutable audit log, enforced at the database level (report 4.6/4.7) ---
    # NOTE: a plain `REVOKE UPDATE, DELETE ... FROM <role>` does NOT work here —
    # Postgres table owners always retain full privileges on their own objects
    # regardless of REVOKE, and the app connects as the owning role in this
    # single-role deployment. A BEFORE trigger that unconditionally raises is
    # enforced for every role, including the owner and superuser, so it's the
    # actual mechanism that makes this append-only rather than just app-layer
    # discipline.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_events_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_events_immutable
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_immutable();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_immutable ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_immutable()")
    op.drop_table("audit_events")
    op.drop_table("system_settings")
    op.drop_table("feedback")
    op.drop_table("ingestion_jobs")
    op.drop_table("entity_resolution_review")
    op.drop_table("edge_candidates")
    op.drop_table("entity_mentions")
    op.drop_table("edges")
    op.drop_table("entities")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("sources")
    op.drop_table("api_keys")
    op.drop_table("users")
    op.execute("DROP FUNCTION IF EXISTS cranus_to_tsvector(text)")
