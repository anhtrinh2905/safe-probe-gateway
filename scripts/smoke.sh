#!/usr/bin/env bash
# Prove each gateway control with curl, independently of the Python tool.
#
# The tool has its own client-side limits, so a 429 seen through the tool proves
# nothing about the gateway. These checks use curl precisely because curl obeys
# nothing: whatever refuses the request here is the gateway.
#
# Evidence lands in reports/evidence/. The API key is never echoed.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# shellcheck disable=SC1091
set -a; source .env; set +a

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8000}"
KEY="${PROBE_API_KEY:?PROBE_API_KEY is not set -- run scripts/up.sh first}"
OUT="reports/evidence"
mkdir -p "$OUT"

pass=0; fail=0

# Records the request, the status, and the gateway's decision header. `-s -D -`
# keeps headers and body together so the file reads like a transcript.
check() {
  local file="$1" want="$2" title="$3"; shift 3
  local shown="${*//$KEY/***REDACTED***}"
  {
    echo "# $title"
    echo "\$ curl -i $shown"
    echo
  } > "$OUT/$file"

  local body status
  body="$(curl -s -i --max-time 30 "$@" 2>&1)"
  status="$(printf '%s' "$body" | awk 'NR==1{print $2}')"
  # Bodies can be hundreds of KB; the first 40 lines are the evidence.
  printf '%s\n' "$body" | head -40 | sed "s/$KEY/***REDACTED***/g" >> "$OUT/$file"

  if [[ "$status" == "$want" ]]; then
    echo "  PASS  $title -> $status"
    ((pass++))
  else
    echo "  FAIL  $title -> got $status, want $want"
    ((fail++))
  fi
  echo "expected $want, got $status" >> "$OUT/$file"
}

echo "== 1. targets are not reachable except through the gateway =="
{
  echo "# juice-shop publishes no ports (docker-compose.yml, network internal: true)."
  echo "\$ curl --max-time 2 http://localhost:3000/   # juice-shop"
  curl -s --max-time 2 "http://localhost:3000/" 2>&1 || true
  echo
  echo "\$ docker inspect -f '{{json .NetworkSettings.Ports}}' w4-juice-shop"
  docker inspect -f '{{.Name}} {{json .NetworkSettings.Ports}}' w4-juice-shop 2>&1 || true
} > "$OUT/juice-shop-01-no-direct-access.txt"
{
  echo "# lab-app publishes no ports (docker-compose.yml, network internal: true)."
  echo "\$ curl --max-time 2 http://localhost:8080/health   # lab-app"
  curl -s --max-time 2 "http://localhost:8080/health" 2>&1 || true
  echo
  echo "\$ docker inspect -f '{{json .NetworkSettings.Ports}}' w4-lab-app"
  docker inspect -f '{{.Name}} {{json .NetworkSettings.Ports}}' w4-lab-app 2>&1 || true
} > "$OUT/lab-app-01-no-direct-access.txt"
if curl -fsS --max-time 2 "http://localhost:3000/" >/dev/null 2>&1; then
  echo "  FAIL  juice-shop is reachable directly"; ((fail++))
else
  echo "  PASS  juice-shop is not reachable directly"; ((pass++))
fi
if curl -fsS --max-time 2 "http://localhost:8080/health" >/dev/null 2>&1; then
  echo "  FAIL  lab-app is reachable directly"; ((fail++))
else
  echo "  PASS  lab-app is not reachable directly"; ((pass++))
fi

echo "== 2. allowlist =="
check juice-shop-02-allowed-200.txt 200 "GET /api/Products with a valid key" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/api/Products"
check juice-shop-03-blocked-ftp.txt 404 "GET /ftp (week 3 TP-4, now off the allowlist)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/ftp"
check juice-shop-04-blocked-basket.txt 404 "GET /rest/basket/1 (week 3 TP-5 IDOR, now off the allowlist)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/rest/basket/1"
check juice-shop-05-blocked-users.txt 404 "GET /api/Users (reads other people's data)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/api/Users"

echo "== 3. api key =="
check juice-shop-06-no-key-401.txt 401 "GET /api/Products with no key" \
  "$GATEWAY_URL/api/Products"
check juice-shop-07-wrong-key-401.txt 401 "GET /api/Products with a wrong key" \
  -H "X-API-Key: definitely-not-the-key" "$GATEWAY_URL/api/Products"

echo "== 4. method and acl =="
check juice-shop-08-method-405.txt 405 "POST /api/Products (route is GET only)" \
  -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{}' \
  "$GATEWAY_URL/api/Products"
check juice-shop-09-forbidden-403.txt 403 "GET /metrics (route exists, agent-tool lacks the 'admin' group)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/metrics"

echo "== 5. lab-app: auth (401) =="
# ACL 403 for lab is not separately proven: every lab route is group `probe`,
# same as agent-tool. The 403 path in the flowchart is covered by juice-shop /metrics.
check lab-app-05-no-key-401.txt 401 "POST /echo with no key" \
  -X POST -H "Content-Type: application/json" -d '{"msg":"hello"}' "$GATEWAY_URL/echo"
check lab-app-06-wrong-key-401.txt 401 "POST /echo with a wrong key" \
  -X POST -H "X-API-Key: definitely-not-the-key" -H "Content-Type: application/json" \
  -d '{"msg":"hello"}' "$GATEWAY_URL/echo"

echo "== 6. lab-app: allowlist (404) =="
# /health and /items exist on lab-app but are deliberately absent from policy.yml.
check lab-app-07-blocked-health-404.txt 404 "GET /health (lab-app path, not in allowlist)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/health"
check lab-app-08-blocked-items-404.txt 404 "GET /items (lab-app path, not in allowlist)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/items"

echo "== 7. lab-app: request size (413) =="
# 128 KB against a 64 KB cap. Sent from a file so curl sets Content-Length and
# the gateway can refuse before reading the body.
python3 -c "open('/tmp/w4-oversized.json','w').write('{\"q\":\"' + 'A'*131072 + '\"}')"
check lab-app-02-request-413.txt 413 "POST /echo with a 128 KB body (cap is 64 KB)" \
  -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  --data-binary @/tmp/w4-oversized.json "$GATEWAY_URL/echo"

echo "== 8. lab-app: proxy allowed paths =="
check lab-app-09-echo-allowed-200.txt 200 "POST /echo reflects the payload" \
  -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"msg":"hello"}' "$GATEWAY_URL/echo"
check lab-app-10-status-418.txt 418 "GET /status/418 echoes the status code" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/status/418"

echo "== 9. lab-app: upstream timeout (504) =="
check lab-app-03-upstream-timeout-504.txt 504 "GET /slow?ms=9000 (gateway gives up at 5s)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/slow?ms=9000"

echo "== 10. lab-app: response size (truncate) =="
{
  echo "# GET /big?kb=500 -- upstream returns 500 KB, gateway caps at 256 KB."
  echo "\$ curl -sD - -o /tmp/w4-big.bin '\$GATEWAY_URL/big?kb=500'"
  echo
  curl -s -D - -o /tmp/w4-big.bin -H "X-API-Key: $KEY" "$GATEWAY_URL/big?kb=500" \
    | sed "s/$KEY/***REDACTED***/g"
  echo
  echo "bytes actually received: $(wc -c < /tmp/w4-big.bin)"
  echo "max_response_bytes:      262144"
} > "$OUT/lab-app-04-response-truncated.txt"
got=$(wc -c < /tmp/w4-big.bin | tr -d ' ')
if [[ "$got" == "262144" ]]; then
  echo "  PASS  response truncated at 262144 bytes"; ((pass++))
else
  echo "  FAIL  response was $got bytes, want 262144"; ((fail++))
fi

echo "== 11. rate limit (last: it deliberately empties the bucket) =="
{
  echo "# 45 requests as fast as curl can send them. Limit is 30/minute."
  echo
  # sort | uniq -c rather than an associative array: macOS ships bash 3.2,
  # which has none, and this script has to run where the repo runs.
  for _ in $(seq 1 45); do
    curl -s -o /dev/null -w '%{http_code}\n' -H "X-API-Key: $KEY" \
      "$GATEWAY_URL/rest/admin/application-version"
  done | sort | uniq -c | while read -r count code; do echo "  HTTP $code : $count"; done
  echo
  echo "# The 429 in full, with Retry-After:"
  curl -s -i -H "X-API-Key: $KEY" "$GATEWAY_URL/rest/admin/application-version" \
    | head -20 | sed "s/$KEY/***REDACTED***/g"
} > "$OUT/juice-shop-10-rate-limit-429.txt"
if grep -q "HTTP 429" "$OUT/juice-shop-10-rate-limit-429.txt"; then
  echo "  PASS  gateway returned 429 once the bucket emptied"; ((pass++))
else
  echo "  FAIL  no 429 seen in 45 requests"; ((fail++))
fi
# Same consumer bucket: a lab-app route is refused the same way once empty.
check lab-app-11-rate-limit-429.txt 429 "GET /status/200 after the bucket is empty" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/status/200"

echo "== 12. the gateway's own audit log holds no key =="
if grep -rqF "$KEY" data/gateway/ 2>/dev/null; then
  echo "  FAIL  API key found in data/gateway/"; ((fail++))
else
  echo "  PASS  API key does not appear in data/gateway/"; ((pass++))
  { echo "# grep -rF '<PROBE_API_KEY>' data/gateway/  -> no match";
    echo "# lines in the gateway audit log: $(cat data/gateway/*.jsonl 2>/dev/null | wc -l)";
    echo; echo "# a sample entry:";
    tail -1 data/gateway/access.jsonl 2>/dev/null; } > "$OUT/gateway-01-log-clean.txt"
fi

rm -f /tmp/w4-oversized.json /tmp/w4-big.bin
echo
echo "smoke: $pass passed, $fail failed  (evidence in $OUT/)"
[[ "$fail" -eq 0 ]]
