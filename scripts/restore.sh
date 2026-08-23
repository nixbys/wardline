#!/usr/bin/env bash
# Restores a backup created by backup.sh. DESTRUCTIVE: overwrites current
# data. Usage: scripts/restore.sh backups/<timestamp>
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 backups/<timestamp>" >&2
  exit 1
fi
IN="$(cd "$1" && pwd)"
COMPOSE="docker compose -f docker/docker-compose.yml"

read -r -p "This overwrites the current Postgres/Neo4j/MinIO data with the backup at ${IN}. Type 'yes' to continue: " CONFIRM
[ "$CONFIRM" = "yes" ] || { echo "Aborted."; exit 1; }

echo "==> Postgres"
$COMPOSE exec -T postgres pg_restore -U "${POSTGRES_USER:-wardline}" -d "${POSTGRES_DB:-wardline}" \
  --clean --if-exists < "${IN}/postgres.dump"

echo "==> Neo4j (requires downtime)"
$COMPOSE stop neo4j
$COMPOSE cp "${IN}/neo4j.dump" neo4j:/data/dumps/neo4j.dump 2>/dev/null || true
$COMPOSE run --rm --entrypoint /bin/bash neo4j -c \
  "mkdir -p /data/dumps && cp /data/dumps/neo4j.dump /tmp/ 2>/dev/null; neo4j-admin database load neo4j --from-path=/data/dumps --overwrite-destination=true"
$COMPOSE start neo4j

echo "==> MinIO"
$COMPOSE run --rm -v "${IN}/minio:/backup" --entrypoint /bin/sh minio-init -c "
  mc alias set restore-target http://minio:9000 ${S3_ACCESS_KEY:-wardline} ${S3_SECRET_KEY:-wardline-dev-secret} &&
  mc mirror /backup restore-target/${S3_BUCKET:-wardline-bronze}
"

echo "==> Done. Restart api/worker so any in-memory caches pick up the restored state:"
echo "    docker compose -f docker/docker-compose.yml restart api worker"
