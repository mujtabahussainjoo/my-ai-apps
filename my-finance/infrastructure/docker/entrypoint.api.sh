#!/bin/sh
set -eu
exec /usr/local/bin/entrypoint.common.sh uvicorn apps.api.main:app --host 0.0.0.0 --port 8000 "$@"
