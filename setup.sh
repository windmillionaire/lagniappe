#!/bin/sh
set -eu

LAGNIAPPE_REPOSITORY_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
LAGNIAPPE_VENV_PYTHON="$LAGNIAPPE_REPOSITORY_ROOT/venv/bin/python"
cd -- "$LAGNIAPPE_REPOSITORY_ROOT"

supported_python() {
    "$1" -E -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' \
        >/dev/null 2>&1
}

if [ ! -x "$LAGNIAPPE_VENV_PYTHON" ]; then
    printf '%s\n' "Preparing Lagniappe's isolated Python environment..."
    LAGNIAPPE_BOOTSTRAP_PYTHON=""

    for LAGNIAPPE_PYTHON_CANDIDATE in python3 python; do
        if command -v "$LAGNIAPPE_PYTHON_CANDIDATE" >/dev/null 2>&1 \
            && supported_python "$LAGNIAPPE_PYTHON_CANDIDATE"; then
            LAGNIAPPE_BOOTSTRAP_PYTHON=$LAGNIAPPE_PYTHON_CANDIDATE
            break
        fi
    done

    if [ -z "$LAGNIAPPE_BOOTSTRAP_PYTHON" ] \
        && command -v gcloud >/dev/null 2>&1; then
        LAGNIAPPE_BOOTSTRAP_PYTHON=$(
            gcloud info --format=value\(basic.python_location\) 2>/dev/null || true
        )
        if [ -z "$LAGNIAPPE_BOOTSTRAP_PYTHON" ] \
            || [ ! -x "$LAGNIAPPE_BOOTSTRAP_PYTHON" ] \
            || ! supported_python "$LAGNIAPPE_BOOTSTRAP_PYTHON"; then
            LAGNIAPPE_BOOTSTRAP_PYTHON=""
        fi
    fi

    if [ -z "$LAGNIAPPE_BOOTSTRAP_PYTHON" ]; then
        printf '%s\n' \
            "" \
            "Lagniappe needs Python 3.12 or newer." \
            "Install a current Google Cloud CLI with bundled Python, or install" \
            "Python 3.12 or newer, reopen this terminal, and run ./setup.sh again."
        exit 1
    fi

    if ! "$LAGNIAPPE_BOOTSTRAP_PYTHON" -E -m venv \
        "$LAGNIAPPE_REPOSITORY_ROOT/venv"; then
        printf '%s\n' \
            "" \
            "Python could not create Lagniappe's isolated environment." \
            "Repair or reinstall Python or Google Cloud CLI, then run ./setup.sh again."
        exit 1
    fi
    printf '%s\n\n' "Lagniappe's isolated Python environment is ready."
fi

exec "$LAGNIAPPE_VENV_PYTHON" -E -m installer "$@"
