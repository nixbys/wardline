-- Runs once, on first container start (mounted into /docker-entrypoint-initdb.d).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
