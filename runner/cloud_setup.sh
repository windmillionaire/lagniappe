#!/usr/bin/env bash
# Reusable Cloud image setup. Run in a fresh checkout before publishing the image.
set -euo pipefail
cd "$(dirname "$0")/.."
worktree=false
case "$#:${1:-}" in
    0:) ;;
    1:--worktree) worktree=true ;;
    *) echo 'Usage: bash runner/cloud_setup.sh [--worktree]' >&2; exit 2 ;;
esac
if ! "$worktree" && [[ -d config/files && -n "$(find config/files -type f -print -quit)" ]]; then
    echo 'Use a clean checkout for the reusable Cloud image. Installation settings are present.' >&2
    exit 1
fi
if ! "$worktree"; then
    command -v gcloud >/dev/null
    command -v gh >/dev/null
fi
if [[ -L venv || -L mcp/.venv ]]; then
    echo 'Create Python and MCP environments inside this worktree. A linked environment cannot be updated safely.' >&2
    exit 1
fi
node_version=$(cat .nvmrc)
if ! command -v node >/dev/null || [[ "$(node -p 'process.versions.node')" != "$node_version" ]]; then
    nvm_script="${NVM_DIR:-$HOME/.nvm}/nvm.sh"
    if [[ ! -r "$nvm_script" ]]; then
        echo "Select Node $node_version or install nvm in this environment." >&2
        exit 1
    fi
    # shellcheck source=/dev/null
    source "$nvm_script" --no-use
    nvm install "$node_version"
    nvm alias default "$node_version"
fi
if [[ ! -x venv/bin/python ]]; then
    python3.14 -m venv venv
elif ! venv/bin/python -c 'import sys; sys.exit(sys.version_info[:2] != (3, 14))'; then
    echo 'Cloud setup requires Python 3.14. Move the existing venv aside and run setup again.' >&2
    exit 1
fi
venv/bin/python -m pip install -r requirements-dev.txt
npm ci --cache "${npm_config_cache:-${NPM_CONFIG_CACHE:-$PWD/venv/.npm-cache}}"
if ! "$worktree"; then
    venv/bin/python -m playwright install chromium
    venv/bin/python -c 'from playwright.sync_api import sync_playwright; p = sync_playwright().start(); p.chromium.launch().close(); p.stop()'
fi
venv/bin/python -m runner.uv_bootstrap install --non-interactive
venv/bin/python -c 'from runner.mcp_environment import prepare_environment; prepare_environment()'
