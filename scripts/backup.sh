#!/usr/bin/env bash
# Backs up Postgres, Neo4j, and MinIO into ./backups/<timestamp>/.
#
# Neo4j 5 Community Edition only supports offline dumps (no hot backup —
# that's an Enterprise Edition feature), so this briefly stops the neo4j
# container around its dump. Postgres and MinIO backups are online (no
# downtime). Run from the repo root.
set -euo pipefail

COMPOSE="docker compose -f docker/docker-compose.yml"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT="$(pwd)/backups/${STAMP}"
mkdir -p "${OUT}/minio"

echo "==> Postgres (pg_dump, online)"
$COMPOSE exec -T postgres pg_dump -U "${POSTGRES_USER:-wardline}" -d "${POSTGRES_DB:-wardline}" \
  --format=custom > "${OUT}/postgres.dump"

echo "==> Neo4j (neo4j-admin dump, requires brief downtime)"
$COMPOSE stop neo4j
# --to-path writes into the neo4j_data named volume (mounted at /data by the
# service definition), which `run` reuses — the dump survives this ephemeral
# container being removed.
$COMPOSE run --rm --entrypoint /bin/bash neo4j -c \
  "mkdir -p /data/dumps && neo4j-admin database dump neo4j --to-path=/data/dumps --overwrite-destination=true"
$COMPOSE start neo4j
$COMPOSE exec -T neo4j test -f /data/dumps/neo4j.dump  # wait-ish: fails fast if the dump didn't land
$COMPOSE cp neo4j:/data/dumps/neo4j.dump "${OUT}/neo4j.dump"

echo "==> MinIO (mc mirror, online)"
$COMPOSE run --rm -v "${OUT}/minio:/backup" --entrypoint /bin/sh minio-init -c "
  mc alias set backup-source http://minio:9000 ${S3_ACCESS_KEY:-wardline} ${S3_SECRET_KEY:-wardline-dev-secret} &&
  mc mirror backup-source/${S3_BUCKET:-wardline-bronze} /backup
"

echo "==> Done: ${OUT}"
echo "    Copy this directory off-host (S3, another machine, etc) — a backup"
echo "    that lives on the same disk as what it backs up isn't a backup."
