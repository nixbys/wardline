#!/usr/bin/env bash
# Stands up a dedicated docker-compose stack for one Path A customer
# (docs/COMMERCIALIZATION_ROADMAP.md's "every customer gets their own
# deployment" model) -- the scripted counterpart to the manual `cp
# .env.example .env; scripts/generate_secrets.sh; docker compose up -d;
# ...` sequence in README's Setup section.
#
# usage: scripts/provision_customer.sh <slug> <domain> --admin-email <email>
#          [--extra-env KEY=VALUE ...] [--profile NAME ...]
#
# Run from the repo root.
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "usage: $0 <slug> <domain> --admin-email <email> [--extra-env KEY=VALUE ...] [--profile NAME ...]" >&2
  exit 1
fi

SLUG="$1"
DOMAIN="$2"
shift 2

if ! [[ "$SLUG" =~ ^[a-z0-9-]+$ ]]; then
  echo "error: <slug> must match ^[a-z0-9-]+\$ (got: ${SLUG})" >&2
  exit 1
fi

ADMIN_EMAIL=""
EXTRA_ENV=()
PROFILE_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --admin-email) ADMIN_EMAIL="$2"; shift 2 ;;
    --extra-env) EXTRA_ENV+=("$2"); shift 2 ;;
    --profile) PROFILE_ARGS+=(--profile "$2"); shift 2 ;;
    *) echo "error: unrecognized argument: $1" >&2; exit 1 ;;
  esac
done
[ -n "$ADMIN_EMAIL" ] || { echo "error: --admin-email is required" >&2; exit 1; }

DIR="deployments/${SLUG}"
ENV_FILE="${DIR}/.env"
OVERRIDE_FILE="${DIR}/docker-compose.override.yml"
PROJECT="wardline-${SLUG}"
COMPOSE="docker compose -p ${PROJECT} -f docker/docker-compose.yml -f ${OVERRIDE_FILE} --env-file ${ENV_FILE}"

if [ -e "$DIR" ]; then
  echo "error: ${DIR} already exists -- pick a different slug, or use deprovision_customer.sh first" >&2
  exit 1
fi
mkdir -p "$DIR"

echo "==> Seeding ${ENV_FILE}"
cp .env.example "$ENV_FILE"

# Replaces an existing KEY= line in $ENV_FILE (e.g. APP_BASE_URL, already
# present with a dev default in .env.example) or appends a new one (e.g.
# DOMAIN, which .env.example doesn't define at all) -- never both, so a
# customer's .env never ends up with two conflicting lines for one key.
upsert_env() {
  local key="${1%%=*}"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s|^${key}=.*|${1}|" "$ENV_FILE"
  else
    echo "$1" >> "$ENV_FILE"
  fi
}

upsert_env "DOMAIN=${DOMAIN}"
upsert_env "APP_BASE_URL=https://${DOMAIN}"
for kv in "${EXTRA_ENV[@]+"${EXTRA_ENV[@]}"}"; do
  upsert_env "$kv"
done
scripts/generate_secrets.sh --env-file "$ENV_FILE"

echo "==> Allocating host ports"
# Every previously provisioned customer gets a 100-wide block of ports below
# it, so a fresh instance's block starts clear of every other one on this
# host. A monotonic counter (not "count existing deployments/ dirs") so a
# deprovisioned slug's ports are never handed to a new customer while an
# older stack using neighboring ports might still be running.
COUNTER_FILE="deployments/.next-instance-index"
mkdir -p deployments
[ -f "$COUNTER_FILE" ] || echo 0 > "$COUNTER_FILE"
INSTANCE_INDEX=$(cat "$COUNTER_FILE")
echo $((INSTANCE_INDEX + 1)) > "$COUNTER_FILE"
OFFSET=$((INSTANCE_INDEX * 100))
upsert_env "HTTP_PORT=$((8080 + OFFSET))"
upsert_env "HTTPS_PORT=$((8443 + OFFSET))"
upsert_env "API_HOST_PORT=$((8000 + OFFSET))"
upsert_env "POSTGRES_HOST_PORT=$((5432 + OFFSET))"
upsert_env "NEO4J_HTTP_HOST_PORT=$((7474 + OFFSET))"
upsert_env "NEO4J_BOLT_HOST_PORT=$((7687 + OFFSET))"
upsert_env "MINIO_HOST_PORT=$((9000 + OFFSET))"
upsert_env "MINIO_CONSOLE_HOST_PORT=$((9001 + OFFSET))"

echo "==> Writing ${OVERRIDE_FILE}"
# docker-compose.yml points migrator/api/worker at env_file: ../.env (the
# repo-root .env, shared by the default local-dev stack) -- that path is
# fixed relative to the compose file, not to --env-file, so running a
# second stack needs this override to actually load THIS customer's .env
# instead. (--env-file above still does real work of its own: it's what
# postgres/neo4j/minio/caddy's ${VAR} substitutions and the ports just
# above resolve against.)
ABS_ENV_FILE="$(cd "$DIR" && pwd)/.env"
cat > "$OVERRIDE_FILE" <<EOF
services:
  migrator:
    env_file: ${ABS_ENV_FILE}
  api:
    env_file: ${ABS_ENV_FILE}
  worker:
    env_file: ${ABS_ENV_FILE}
EOF

echo "==> Starting the stack (project: ${PROJECT})"
$COMPOSE up -d "${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"}"

echo "==> Waiting for api to become healthy"
API_PORT=$(grep '^API_HOST_PORT=' "$ENV_FILE" | cut -d= -f2)
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:${API_PORT}/healthz" || true)
  [ "$code" = "200" ] && break
  sleep 2
done
if [ "$code" != "200" ]; then
  echo "error: api never became healthy -- check: $COMPOSE logs api" >&2
  exit 1
fi

echo "==> Running migrations (belt-and-suspenders: the migrator service already ran once)"
$COMPOSE run --rm api python -m alembic upgrade head

echo "==> Creating the first admin user"
ADMIN_OUTPUT=$($COMPOSE run --rm api python -m wardline.cli create-admin-user "$ADMIN_EMAIL")
echo "$ADMIN_OUTPUT" | grep -v '^api_key='
KEY_FILE="${DIR}/admin-api-key.txt"
# cli.py's create-admin-user prints "api_key=<key>  (shown once...)" -- the
# key itself (secrets.token_urlsafe, common/security.py) never contains
# whitespace, so the first field after stripping the prefix is exactly it.
echo "$ADMIN_OUTPUT" | grep '^api_key=' | sed 's/^api_key=//' | awk '{print $1}' > "$KEY_FILE"
chmod 600 "$KEY_FILE"

cat <<SUMMARY

==> Done.
    Stack:      ${PROJECT}
    Domain:     ${DOMAIN}
    Admin user: ${ADMIN_EMAIL}
    Admin key:  ${KEY_FILE}  (chmod 600 -- move it to a real secrets
                manager and delete this file; it's a one-time credential
                that can't be recovered once lost, only rotated)

    Still manual, not done by this script:
      - Point DNS for ${DOMAIN} at this host so Caddy can obtain a real
        Let's Encrypt certificate (it's currently serving its own
        locally-trusted CA until DNS resolves here).
      - Deploy the web/ static frontend -- no compose service serves it;
        that's a separate deployment step wherever you host static files.
SUMMARY
