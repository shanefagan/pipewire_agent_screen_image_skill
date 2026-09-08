#!/usr/bin/env bash
#
# Helper script to execute PipeWire screen capture for Antigravity and other agents.
# Resolves symlinks so it can be called from anywhere (e.g. ~/.local/bin/agent-screen-capture).
#

set -euo pipefail

# Resolve symlinks to find the true script directory
SOURCE="${BASH_SOURCE[0]}"
while [ -h "${SOURCE}" ]; do
    DIR="$(cd -P "$(dirname "${SOURCE}")" && pwd)"
    SOURCE="$(readlink "${SOURCE}")"
    [[ "${SOURCE}" != /* ]] && SOURCE="${DIR}/${SOURCE}"
done
SCRIPT_DIR="$(cd -P "$(dirname "${SOURCE}")" && pwd)"

PYTHON_BIN="$(which python3 || echo "python3")"

exec "${PYTHON_BIN}" "${SCRIPT_DIR}/capture.py" "$@"
