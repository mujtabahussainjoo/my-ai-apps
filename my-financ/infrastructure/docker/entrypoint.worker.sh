#!/bin/sh
set -eu
exec /usr/local/bin/entrypoint.common.sh python -m apps.worker.main "$@"
