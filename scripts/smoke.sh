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
  echo "# Targets publish no ports (docker-compose.yml, network internal: true)."
  echo "\$ curl --max-time 2 http://localhost:3000/   # juice-shop"
  curl -s --max-time 2 "http://localhost:3000/" 2>&1 || true
  echo
  echo "\$ curl --max-time 2 http://localhost:8080/health   # lab-app"
  curl -s --max-time 2 "http://localhost:8080/health" 2>&1 || true
  echo
  echo "\$ docker inspect -f '{{json .NetworkSettings.Ports}}' w4-juice-shop w4-lab-app"
  docker inspect -f '{{.Name}} {{json .NetworkSettings.Ports}}' w4-juice-shop w4-lab-app 2>&1 || true
} > "$OUT/01-no-direct-access.txt"
if curl -fsS --max-time 2 "http://localhost:3000/" >/dev/null 2>&1; then
  echo "  FAIL  juice-shop is reachable directly"; ((fail++))
else
  echo "  PASS  juice-shop is not reachable directly"; ((pass++))
fi

echo "== 2. allowlist =="
check 02-allowed-200.txt 200 "GET /api/Products with a valid key" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/api/Products"
check 03-blocked-ftp.txt 404 "GET /ftp (week 3 TP-4, now off the allowlist)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/ftp"
check 04-blocked-basket.txt 404 "GET /rest/basket/1 (week 3 TP-5 IDOR, now off the allowlist)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/rest/basket/1"
check 05-blocked-users.txt 404 "GET /api/Users (reads other people's data)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/api/Users"

echo "== 3. api key =="
check 06-no-key-401.txt 401 "GET /api/Products with no key" \
  "$GATEWAY_URL/api/Products"
check 07-wrong-key-401.txt 401 "GET /api/Products with a wrong key" \
  -H "X-API-Key: definitely-not-the-key" "$GATEWAY_URL/api/Products"

echo "== 4. method and acl =="
check 08-method-405.txt 405 "POST /api/Products (route is GET only)" \
  -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{}' \
  "$GATEWAY_URL/api/Products"
check 09-forbidden-403.txt 403 "GET /metrics (route exists, agent-tool lacks the 'admin' group)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/metrics"

echo "== 5. request size =="
# 128 KB against a 64 KB cap. Sent from a file so curl sets Content-Length and
# the gateway can refuse before reading the body.
python3 -c "open('/tmp/w4-oversized.json','w').write('{\"q\":\"' + 'A'*131072 + '\"}')"
check 10-request-413.txt 413 "POST /echo with a 128 KB body (cap is 64 KB)" \
  -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  --data-binary @/tmp/w4-oversized.json "$GATEWAY_URL/echo"

echo "== 6. upstream timeout =="
check 11-upstream-timeout-504.txt 504 "GET /slow?ms=9000 (gateway gives up at 5s)" \
  -H "X-API-Key: $KEY" "$GATEWAY_URL/slow?ms=9000"

echo "== 7. response size =="
{
  echo "# GET /big?kb=500 -- upstream returns 500 KB, gateway caps at 256 KB."
  echo "\$ curl -sD - -o /tmp/w4-big.bin '\$GATEWAY_URL/big?kb=500'"
  echo
  curl -s -D - -o /tmp/w4-big.bin -H "X-API-Key: $KEY" "$GATEWAY_URL/big?kb=500" \
    | sed "s/$KEY/***REDACTED***/g"
  echo
  echo "bytes actually received: $(wc -c < /tmp/w4-big.bin)"
  echo "max_response_bytes:      262144"
} > "$OUT/12-response-truncated.txt"
got=$(wc -c < /tmp/w4-big.bin | tr -d ' ')
if [[ "$got" == "262144" ]]; then
  echo "  PASS  response truncated at 262144 bytes"; ((pass++))
else
  echo "  FAIL  response was $got bytes, want 262144"; ((fail++))
fi

echo "== 8. rate limit (last: it deliberately empties the bucket) =="
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
} > "$OUT/13-rate-limit-429.txt"
if grep -q "HTTP 429" "$OUT/13-rate-limit-429.txt"; then
  echo "  PASS  gateway returned 429 once the bucket emptied"; ((pass++))
else
  echo "  FAIL  no 429 seen in 45 requests"; ((fail++))
fi

echo "== 9. the gateway's own audit log holds no key =="
if grep -rqF "$KEY" data/gateway/ 2>/dev/null; then
  echo "  FAIL  API key found in data/gateway/"; ((fail++))
else
  echo "  PASS  API key does not appear in data/gateway/"; ((pass++))
  { echo "# grep -rF '<PROBE_API_KEY>' data/gateway/  -> no match";
    echo "# lines in the gateway audit log: $(cat data/gateway/*.jsonl 2>/dev/null | wc -l)";
    echo; echo "# a sample entry:";
    tail -1 data/gateway/access.jsonl 2>/dev/null; } > "$OUT/14-gateway-log-clean.txt"
fi

rm -f /tmp/w4-oversized.json /tmp/w4-big.bin
echo
echo "smoke: $pass passed, $fail failed  (evidence in $OUT/)"
[[ "$fail" -eq 0 ]]
