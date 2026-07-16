#!/usr/bin/env bash
# One-command demo. Starts cc-wake locally with control enabled (loopback
# only, so it's safe) and opens the dashboard. Ctrl-C to stop.
#
# Requires: python3 (stdlib only). Control actions additionally need macOS +
# Ghostty + Accessibility permission for your terminal; on other setups the
# dashboard still shows your sessions read-only.
set -e
cd "$(dirname "$0")"

PORT="${PORT:-8787}"
echo "starting cc-wake on http://127.0.0.1:$PORT  (control enabled, loopback only)"
( sleep 1; command -v open >/dev/null && open "http://127.0.0.1:$PORT" || true ) &
exec python3 -m cc_wake --port "$PORT" --enable-control
