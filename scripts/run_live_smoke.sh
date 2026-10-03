#!/usr/bin/env bash
set -euo pipefail
: "${SLICER_BIN:=Slicer}"
: "${DCC_MCP_SLICER_WORKSPACE:?Use a new empty artifact directory}"
repo="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$DCC_MCP_SLICER_WORKSPACE"
export DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS=1
exec "$SLICER_BIN" --no-splash --no-main-window --disable-settings --python-script "$repo/scripts/live_smoke.py"
