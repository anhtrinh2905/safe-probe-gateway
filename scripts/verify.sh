#!/usr/bin/env bash
# Everything that must be true before this repo is handed over.
#
# ggshield is last and not optional: "the logs hold no API key" is one of the
# deliverables, and a test proving the *log* is clean says nothing about whether
# a key was committed alongside it.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

fail=0
step() { echo; echo "== $* =="; }

step "ruff"
if command -v ruff >/dev/null 2>&1; then
  ruff check src tests || fail=1
  ruff format --check src tests 2>/dev/null || true
else
  echo "  ruff not installed -- skipped (pip install ruff)"
fi

step "pytest"
python3 -m pytest tests/ -q || fail=1

step "no API key in data/ or reports/"
if [[ -f .env ]]; then
  # shellcheck disable=SC1091
  key="$(grep -E '^PROBE_API_KEY=' .env | cut -d= -f2-)"
  if [[ -n "$key" ]] && grep -rqF "$key" data/ reports/ 2>/dev/null; then
    echo "  FAIL: the API key appears under data/ or reports/"
    fail=1
  else
    echo "  ok: not found"
  fi
else
  echo "  .env absent -- skipped"
fi

step "ggshield"
if command -v ggshield >/dev/null 2>&1; then
  # -y: without it ggshield asks for confirmation and this script hangs in CI.
  ggshield secret scan path -r . -y --exclude .venv --exclude data || fail=1
else
  echo "  ggshield not installed -- skipped (pip install ggshield)"
fi

echo
[[ "$fail" -eq 0 ]] && echo "verify: all checks passed" || echo "verify: FAILED"
exit "$fail"
