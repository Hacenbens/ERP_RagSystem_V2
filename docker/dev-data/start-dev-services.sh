#!/usr/bin/env bash
#
# Start isolated PostgreSQL and MongoDB containers for local testing.
#
# Deliberately NOT the compose stack: these are throwaway fixtures with seeded
# data and development passwords, on non-default host ports so they cannot
# collide with a MongoDB or PostgreSQL already running on this machine.
#
#   ./docker/dev-data/start-dev-services.sh          # start (idempotent)
#   ./docker/dev-data/start-dev-services.sh --reset  # destroy data and reseed
#   ./docker/dev-data/start-dev-services.sh --stop   # remove containers
#
# The credentials below are development-only and are meant to be committed.
# Never reuse them anywhere reachable from outside this machine.
set -euo pipefail

PG_CONTAINER=erp_rag_pg_dev
MONGO_CONTAINER=erp_rag_mongo_dev
PG_VOLUME=erp_rag_pg_dev_data
MONGO_VOLUME=erp_rag_mongo_dev_data

PG_PORT=55432          # not 5432 — leaves an existing local PostgreSQL alone
MONGO_PORT=57017       # not 27017 — same reason

PG_DB=erp_prod
PG_ADMIN_USER=erp_admin
PG_ADMIN_PASSWORD=erp_admin_dev_pw_2026
PG_RO_USER=erp_readonly
PG_RO_PASSWORD=erp_ro_dev_pw_2026        # created by erp_seed.sql

MONGO_USER=erp_root
MONGO_PASSWORD=erp_root_dev_pw_2026

SEED_SQL="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/erp_seed.sql"

case "${1:-start}" in
  --stop)
    docker rm -f "$PG_CONTAINER" "$MONGO_CONTAINER" >/dev/null 2>&1 || true
    echo "stopped and removed both containers (data volumes kept)"
    exit 0
    ;;
  --reset)
    docker rm -f "$PG_CONTAINER" "$MONGO_CONTAINER" >/dev/null 2>&1 || true
    docker volume rm "$PG_VOLUME" "$MONGO_VOLUME" >/dev/null 2>&1 || true
    echo "removed containers and data volumes — will reseed"
    ;;
esac

# PostgreSQL. The seed only runs when the data directory is empty, which is
# how the official image works: after --reset, or on a first start.
if ! docker ps --format '{{.Names}}' | grep -qx "$PG_CONTAINER"; then
  docker rm -f "$PG_CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$PG_CONTAINER" \
    -e POSTGRES_DB="$PG_DB" \
    -e POSTGRES_USER="$PG_ADMIN_USER" \
    -e POSTGRES_PASSWORD="$PG_ADMIN_PASSWORD" \
    -p "${PG_PORT}:5432" \
    -v "${PG_VOLUME}:/var/lib/postgresql/data" \
    -v "${SEED_SQL}:/docker-entrypoint-initdb.d/01_erp_seed.sql:ro" \
    postgres:16-alpine >/dev/null
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$MONGO_CONTAINER"; then
  docker rm -f "$MONGO_CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$MONGO_CONTAINER" \
    -e MONGO_INITDB_ROOT_USERNAME="$MONGO_USER" \
    -e MONGO_INITDB_ROOT_PASSWORD="$MONGO_PASSWORD" \
    -p "${MONGO_PORT}:27017" \
    -v "${MONGO_VOLUME}:/data/db" \
    mongo:7.0 >/dev/null
fi

echo -n "waiting for postgres"
until docker exec "$PG_CONTAINER" pg_isready -U "$PG_ADMIN_USER" -d "$PG_DB" >/dev/null 2>&1; do
  echo -n .; sleep 1
done; echo " ready"

echo -n "waiting for mongo"
until docker exec "$MONGO_CONTAINER" mongosh --quiet --eval 'db.adminCommand("ping").ok' >/dev/null 2>&1; do
  echo -n .; sleep 1
done; echo " ready"

TABLES=$(docker exec "$PG_CONTAINER" psql -U "$PG_ADMIN_USER" -d "$PG_DB" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")
echo "seeded tables: ${TABLES// /}"

cat <<EOF

Add to .env:

  ERP_PG_HOST=127.0.0.1
  ERP_PG_PORT=${PG_PORT}
  ERP_PG_DATABASE=${PG_DB}
  ERP_PG_USER=${PG_RO_USER}
  ERP_PG_PASSWORD=${PG_RO_PASSWORD}

  MONGODB_URI=mongodb://${MONGO_USER}:${MONGO_PASSWORD}@127.0.0.1:${MONGO_PORT}/?authSource=admin

Run the tests that need them:

  ERP_PG_TEST_DSN=postgresql://${PG_RO_USER}:${PG_RO_PASSWORD}@127.0.0.1:${PG_PORT}/${PG_DB} \\
    pytest src/tests/integration/test_postgres_executor.py
EOF
