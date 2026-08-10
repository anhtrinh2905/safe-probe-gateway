#!/usr/bin/env bash
# Bring up the gateway and both targets, and generate the API key if there is
# not one yet. The key is written to .env (gitignored) and nowhere else.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8000}"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

# Generated rather than chosen: a key someone typed is a key someone remembers,
# and this one only ever needs to exist in .env and the gateway's environment.
if ! grep -qE '^PROBE_API_KEY=.+$' .env; then
  key="$(openssl rand -hex 24)"
  # macOS sed needs the empty -i argument; GNU sed tolerates it via the ''.
  sed -i '' -e "s|^PROBE_API_KEY=.*$|PROBE_API_KEY=${key}|" .env 2>/dev/null \
    || sed -i -e "s|^PROBE_API_KEY=.*$|PROBE_API_KEY=${key}|" .env
  echo "Generated PROBE_API_KEY into .env (value not printed on purpose)"
fi

mkdir -p data/gateway data/probe

docker compose up -d --build

echo "Waiting for the gateway ..."
for _ in $(seq 1 60); do
  if curl -fsS "$GATEWAY_URL/_gateway/health" >/dev/null 2>&1; then
    routes=$(curl -fsS "$GATEWAY_URL/_gateway/health")
    echo "Gateway is up at $GATEWAY_URL -> $routes"
    break
  fi
  sleep 2
done

if ! curl -fsS "$GATEWAY_URL/_gateway/health" >/dev/null 2>&1; then
  echo "Gateway did not become healthy in time" >&2
  docker compose logs --tail 60 gateway >&2
  exit 1
fi

# Juice Shop is slow to boot and nothing depends_on it, so wait here rather than
# letting the first probe get a confusing 502. Waited on *through the gateway*:
# the image has no shell and no node/curl/wget on PATH, so an in-container
# healthcheck is impossible -- and a 200 here proves more anyway, since it means
# routing, auth and the upstream are all working.
# shellcheck disable=SC1091
set -a; source .env; set +a
echo "Waiting for juice-shop (via the gateway) ..."
for _ in $(seq 1 90); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "X-API-Key: ${PROBE_API_KEY}" \
    "$GATEWAY_URL/rest/admin/application-version" || true)
  if [[ "$code" == "200" ]]; then
    echo "juice-shop answers through the gateway (no published port, by design)"
    break
  fi
  sleep 2
done

echo
echo "Proof that the targets are only reachable through the gateway:"
for port in 3000 8080; do
  if curl -fsS --max-time 2 "http://localhost:$port/" >/dev/null 2>&1; then
    echo "  localhost:$port  REACHABLE  <-- a target published a port; see AGENTS.md" >&2
    exit 1
  fi
  echo "  localhost:$port  refused"
done
