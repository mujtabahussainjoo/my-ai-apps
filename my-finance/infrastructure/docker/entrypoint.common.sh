#!/bin/sh
# Wait for PostgreSQL, migrate, then hand over to the service.
#
# Compose's `depends_on: service_healthy` covers a cold start, but not Postgres
# restarting underneath a running stack. Waiting here means a service recovering
# from either case behaves the same way.
set -eu

DB_HOST="${POSTGRES_HOST:-postgres}"
DB_PORT="${POSTGRES_PORT:-5432}"
WAIT_SECONDS="${DB_WAIT_SECONDS:-60}"

echo "waiting up to ${WAIT_SECONDS}s for postgres at ${DB_HOST}:${DB_PORT}"
elapsed=0
until python -c "
import os, socket, sys
host, port = os.environ['POSTGRES_HOST'], int(os.environ['POSTGRES_PORT'])
try:
    with socket.create_connection((host, port), timeout=2):
        pass
except OSError:
    sys.exit(1)
"; do
    elapsed=$((elapsed + 1))
    if [ "$elapsed" -ge "$WAIT_SECONDS" ]; then
        echo "postgres not reachable after ${WAIT_SECONDS}s" >&2
        exit 1
    fi
    sleep 1
done
echo "postgres reachable after ${elapsed}s"

# Migrations run before the service starts serving. Two replicas starting at
# once is safe: migrations take an advisory lock and are idempotent.
echo "applying migrations"
python -m src.database.migrate

echo "starting: $*"
exec "$@"
