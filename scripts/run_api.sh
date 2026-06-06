#!/usr/bin/env bash
# Start the local FastAPI server.
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${API_HOST:-127.0.0.1}"
PORT="${API_PORT:-8765}"

exec uv run recording-auto api --host "$HOST" --port "$PORT"
