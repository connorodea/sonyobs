#!/usr/bin/env bash
# Install the project with uv. Idempotent.
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found. Installing via the official installer..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1090
  source "$HOME/.cargo/env" 2>/dev/null || true
  export PATH="$HOME/.local/bin:$PATH"
fi

echo "==> uv sync"
uv sync

echo "==> uv tool install (puts sonyobs / sob / recording-auto on PATH)"
uv tool install --force --no-cache . >/dev/null

if [[ ! -f .env ]]; then
  echo "==> Creating .env from .env.example"
  cp .env.example .env
  echo "    Edit .env and set OBS_PASSWORD before running anything."
fi

if [[ ! -f config.yaml ]]; then
  echo "==> Creating config.yaml from config.example.yaml"
  cp config.example.yaml config.yaml
  echo "    Edit config.yaml so OBS source names match what you set up in OBS."
fi

echo
echo "Install complete."
echo
echo "You can now use any of these from any directory:"
echo "    sonyobs <command>     # primary"
echo "    sob <command>         # short alias"
echo "    recording-auto <cmd>  # original name"
echo
echo "Next:"
echo "  1. Edit .env (set OBS_PASSWORD)"
echo "  2. Edit config.yaml (match OBS source names)"
echo "  3. sonyobs doctor"
echo "  4. sonyobs go          # start recording with default profile"
echo "  5. sonyobs stop"
