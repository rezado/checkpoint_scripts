#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_SCRIPT="/nfs/home/share/workload_env/env.sh"
EXISTING_NEMU_HOME="${NEMU_HOME-}"

if [[ -r "$ENV_SCRIPT" ]]; then
    # shellcheck disable=SC1091
    source "$ENV_SCRIPT"
fi

if [[ -n "$EXISTING_NEMU_HOME" ]]; then
    export NEMU_HOME="$EXISTING_NEMU_HOME"
fi

exec python3 "$SCRIPT_DIR/run_single_bin_checkpoint.py" "$@"
