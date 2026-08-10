#!/usr/bin/env bash
# Tear everything down. `data/` is left alone -- it is disposable, but deleting
# it is a separate decision from stopping the containers.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

docker compose down --remove-orphans "$@"
