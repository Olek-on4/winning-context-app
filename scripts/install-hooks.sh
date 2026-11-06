#!/usr/bin/env bash
# Point git at the checked-in hooks; idempotent, local to this clone.
set -euo pipefail
cd "$(dirname "$0")/.."
git config core.hooksPath .githooks
echo "core.hooksPath set to .githooks (pre-commit runs: make -s check)"
