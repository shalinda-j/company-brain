#!/usr/bin/env sh
# Entrypoint that fixes the bind-mounted data dir ownership before dropping to
# the non-root 'brain' user. This makes a host-mounted ./data writable
# regardless of who created it on the host (fixes the v1 permission bug).
set -e

DATA_DIR="${BRAIN_DATA_DIR:-/data}"
mkdir -p "$DATA_DIR"

# If running as root (default at container start), fix ownership then step down.
if [ "$(id -u)" = "0" ]; then
    chown -R brain:brain "$DATA_DIR" 2>/dev/null || true
    exec gosu brain "$@"
fi

exec "$@"
