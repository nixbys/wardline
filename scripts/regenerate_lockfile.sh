#!/usr/bin/env bash
# Regenerates requirements-lock.txt from the built api image (which has every
# dependency, including transitive ones, actually installed and resolved).
# Run this after changing pyproject.toml's dependencies, then commit the
# result.
set -euo pipefail

docker compose -f docker/docker-compose.yml build api
docker compose -f docker/docker-compose.yml run --rm --no-deps --entrypoint pip api freeze \
  | grep -v '^-e ' > requirements-lock.txt

echo "Wrote requirements-lock.txt ($(wc -l < requirements-lock.txt) packages)."
