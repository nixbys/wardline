#!/usr/bin/env bash
# Generates strong random values for every secret this project needs and
# prints `KEY=value` lines ready to paste into .env (or pipe into a real
# secrets manager instead — see README's Production readiness section for
# why a real deployment shouldn't just leave these in a plaintext .env file).
set -euo pipefail

rand() { openssl rand -base64 "$1" | tr -d '\n=+/' | head -c "$2"; }

cat <<EOF
API_KEY_PEPPER=$(rand 48 48)
PASSWORD_PEPPER=$(rand 48 48)
POSTGRES_PASSWORD=$(rand 32 32)
NEO4J_PASSWORD=$(rand 32 32)
S3_SECRET_KEY=$(rand 32 32)
EOF
