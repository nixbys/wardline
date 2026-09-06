#!/usr/bin/env bash
# Generates strong random values for every secret this project needs and
# prints `KEY=value` lines ready to paste into .env (or pipe into a real
# secrets manager instead — see README's Production readiness section for
# why a real deployment shouldn't just leave these in a plaintext .env file).
#
# --env-file <path>: instead of printing, upsert these lines directly into
# an existing .env file (replacing a matching KEY= line if one exists,
# appending otherwise). Used by scripts/provision_customer.sh to fill in a
# freshly generated per-customer .env non-interactively.
set -euo pipefail

rand() { openssl rand -base64 "$1" | tr -d '\n=+/' | head -c "$2"; }

lines=$(cat <<EOF
API_KEY_PEPPER=$(rand 48 48)
PASSWORD_PEPPER=$(rand 48 48)
POSTGRES_PASSWORD=$(rand 32 32)
NEO4J_PASSWORD=$(rand 32 32)
S3_SECRET_KEY=$(rand 32 32)
EOF
)

if [ "${1:-}" = "--env-file" ]; then
  ENV_FILE="$2"
  [ -f "$ENV_FILE" ] || : > "$ENV_FILE"
  while IFS= read -r line; do
    key="${line%%=*}"
    if grep -q "^${key}=" "$ENV_FILE"; then
      sed -i "s|^${key}=.*|${line}|" "$ENV_FILE"
    else
      echo "$line" >> "$ENV_FILE"
    fi
  done <<< "$lines"
else
  echo "$lines"
fi
