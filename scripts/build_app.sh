#!/usr/bin/env bash
# Build SonyOBS.app — a menu-bar-only macOS app that wraps `sonyobs menubar`.
#
# Output: ./dist/SonyOBS.app
#
# Drag dist/SonyOBS.app to /Applications.
#
# Notes:
# - Requires macOS (py2app is mac-only).
# - Uses the project's `uv`-managed .venv so the bundle picks up the exact
#   versions in uv.lock.
# - The build runs from an isolated `_appbuild/` directory because py2app +
#   modern setuptools choke when a `pyproject.toml` is in scope (setuptools
#   tries to merge `[project]` metadata into `setup()` and fails with
#   "install_requires is no longer supported"). The isolated dir hides
#   pyproject.toml from setuptools while still pointing at the real source via
#   symlink.
# - Bundle is unsigned. For personal use that's fine — first launch needs a
#   right-click → Open to get past Gatekeeper. For distribution, sign +
#   notarize afterward with codesign + xcrun notarytool.

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "build_app.sh: this only runs on macOS (py2app is mac-only)." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "build_app.sh: 'uv' not found on PATH. Install from https://docs.astral.sh/uv/" >&2
  exit 1
fi

echo "==> Syncing dependencies + installing rumps & py2app into .venv"
uv sync --quiet
uv pip install --quiet "rumps>=0.4.0" "py2app>=0.28.0"

PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "build_app.sh: expected $PY to exist after uv sync." >&2
  exit 1
fi

echo "==> Cleaning previous build/ dist/ _appbuild/"
rm -rf build dist _appbuild

echo "==> Preparing isolated build dir (_appbuild) so setuptools ignores pyproject.toml"
mkdir -p _appbuild
cp setup.py _appbuild/setup.py
ln -snf "$ROOT/src" _appbuild/src

echo "==> Running py2app (alias build for fast dev-mode bundle)"
# `--alias` symlinks source into the bundle (fast, less dependency-discovery
# risk). For a redistributable bundle drop --alias and ship dist/SonyOBS.app
# verbatim — that takes longer and may need explicit `packages=` tweaks.
(
  cd _appbuild
  "$PY" setup.py py2app --alias --dist-dir "$ROOT/dist" --bdist-base "$ROOT/build"
)

if [[ -d "$ROOT/dist/SonyOBS.app" ]]; then
  echo
  echo "Built: $ROOT/dist/SonyOBS.app"
  echo
  echo "Launch with:    open $ROOT/dist/SonyOBS.app"
  echo "Install with:   cp -R $ROOT/dist/SonyOBS.app /Applications/"
else
  echo "build_app.sh: build finished but dist/SonyOBS.app is missing." >&2
  exit 1
fi
