#!/usr/bin/env bash
# Tears down a customer stack created by provision_customer.sh. DESTRUCTIVE:
# stops and removes that stack's containers, network, and named volumes
# (Postgres/Neo4j/MinIO data included). Usage: scripts/deprovision_customer.sh <slug>
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <slug>" >&2
  exit 1
fi
SLUG="$1"
DIR="deployments/${SLUG}"
[ -d "$DIR" ] || { echo "error: ${DIR} does not exist" >&2; exit 1; }

COMPOSE="docker compose -p wardline-${SLUG} -f docker/docker-compose.yml -f ${DIR}/docker-compose.override.yml --env-file ${DIR}/.env"

read -r -p "This stops and permanently deletes wardline-${SLUG}'s containers AND data volumes (Postgres/Neo4j/MinIO). Run scripts/backup.sh first if this data must be kept. Type 'yes' to continue: " CONFIRM
[ "$CONFIRM" = "yes" ] || { echo "Aborted."; exit 1; }

echo "==> Stopping and removing wardline-${SLUG} (containers, network, volumes)"
$COMPOSE down --volumes

echo "==> Removing ${DIR}"
rm -rf "$DIR"

echo "==> Done. Note: this does not free wardline-${SLUG}'s allocated port block for reuse"
echo "    (deployments/.next-instance-index only ever increments) -- that's deliberate, so a"
echo "    still-running neighboring stack's ports can never collide with a new one."
