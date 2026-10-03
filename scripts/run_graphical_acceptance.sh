#!/usr/bin/env bash
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
: "${DCC_MCP_SLICER_ACCEPTANCE_ROOT:?Use a new dedicated test directory}"
: "${SLICER_BIN:=/opt/slicer/5.10.0/Slicer}"
: "${DCC_MCP_SLICER_TEST_SITE:=$repo/build/venv/lib/python3.12/site-packages}"
: "${DCC_MCP_SLICER_SDK_PYTHON:=$repo/build/venv/bin/python}"
mkdir -p "$DCC_MCP_SLICER_ACCEPTANCE_ROOT"/{artifacts,home,registry,cache,config,data}
export HOME="$DCC_MCP_SLICER_ACCEPTANCE_ROOT/home"
export XDG_CACHE_HOME="$DCC_MCP_SLICER_ACCEPTANCE_ROOT/cache"
export XDG_CONFIG_HOME="$DCC_MCP_SLICER_ACCEPTANCE_ROOT/config"
export XDG_DATA_HOME="$DCC_MCP_SLICER_ACCEPTANCE_ROOT/data"
export DCC_MCP_SLICER_WORKSPACE="$DCC_MCP_SLICER_ACCEPTANCE_ROOT/artifacts"
export DCC_MCP_REGISTRY_DIR="$DCC_MCP_SLICER_ACCEPTANCE_ROOT/registry"
export DCC_MCP_SLICER_TEST_SITE DCC_MCP_SLICER_SDK_PYTHON
export DCC_MCP_DISABLE_DEFAULT_SKILL_PATHS=1
export DCC_MCP_CHECKPOINT_IN_MEMORY=1
export DCC_MCP_DISABLE_FILE_LOGGING=1
export DCC_MCP_DISABLE_TELEMETRY=1
export DCC_MCP_DISABLE_JOB_PERSISTENCE=1
export DCC_MCP_GATEWAY_PORT=0
# Preserve the caller's existing graphical display/context. Never start Xvfb or
# attach to another Slicer; this command creates its own new process.
exec "$SLICER_BIN" --no-splash --disable-settings --python-script "$repo/scripts/graphical_acceptance.py"
