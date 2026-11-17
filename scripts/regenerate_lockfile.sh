#!/usr/bin/env bash
# Regenerates requirements-lock.txt: every dependency of the package and its
# dev extra, resolved for the Docker images' Python (3.12, x86-64 Linux).
# Run this after changing pyproject.toml's dependencies, then commit the
# result. Needs uv (https://docs.astral.sh/uv/); nothing gets installed.
set -euo pipefail
cd "$(dirname "$0")/.."

uv pip compile pyproject.toml --extra dev \
  --python-version 3.12 --python-platform x86_64-manylinux_2_28 \
  --no-header --no-annotate --quiet -o requirements-lock.txt

echo "Wrote requirements-lock.txt ($(wc -l < requirements-lock.txt) packages)."
