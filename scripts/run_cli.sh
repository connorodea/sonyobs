#!/usr/bin/env bash
# Thin wrapper to run any CLI subcommand: ./scripts/run_cli.sh doctor
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run recording-auto "$@"
