#!/bin/zsh
# Launch the telekinesis engine. Pass --debug-angles to verify axis mapping.
set -euo pipefail
cd "$(dirname "$0")/engine"
exec .venv/bin/python main.py "$@"
