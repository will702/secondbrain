#!/usr/bin/env bash
# End-to-end smoke test of the packaged runtime pieces:
# frozen backend (build/backend) + embedded postgres (build/postgres) +
# static web export (apps/web/out). Exits non-zero on any failure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BACKEND="$ROOT/build/backend/secondbrain-backend"
PG_BIN="$ROOT/build/postgres/bin"
WEB_OUT="$ROOT/apps/web/out"
PORT="${SMOKE_PORT:-8130}"
WORK="$(mktemp -d /tmp/sb-smoke.XXXXXX)"

for f in "$BACKEND" "$PG_BIN/postgres" "$WEB_OUT/index.html"; do
  [[ -e "$f" ]] || { echo "✗ missing $f — run build-backend.sh / build-postgres.sh / pnpm build first" >&2; exit 1; }
done

cleanup() {
  [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
  [[ -n "${BACKEND_PID:-}" ]] && wait "$BACKEND_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "→ launching frozen backend (embedded postgres, port $PORT)"
mkdir -p "$WORK/logs"
env -i PATH=/usr/bin:/bin HOME="$WORK" \
  SECONDBRAIN_MANAGE_DB=1 \
  SECONDBRAIN_POSTGRES_BIN="$PG_BIN" \
  SECONDBRAIN_PGDATA="$WORK/pgdata" \
  SECONDBRAIN_PG_LOG="$WORK/logs/postgres.log" \
  SECONDBRAIN_ENV_FILE=/dev/null \
  WEB_DIST_DIR="$WEB_OUT" \
  DATA_DIR="$WORK/data" \
  LLM_BASE_URL=http://127.0.0.1:9/v1 \
  EMBEDDING_PROVIDER=fake \
  PORT="$PORT" \
  "$BACKEND" 2>"$WORK/logs/backend.log" &
BACKEND_PID=$!

for i in $(seq 1 120); do
  /usr/bin/curl -sf -o /dev/null "http://127.0.0.1:$PORT/healthz" && break
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "✗ backend died during startup:" >&2; tail -20 "$WORK/logs/backend.log" >&2; exit 1
  fi
  sleep 0.5
done
/usr/bin/curl -sf -o /dev/null "http://127.0.0.1:$PORT/healthz" || { echo "✗ backend never became healthy" >&2; exit 1; }
echo "  ✓ healthz"

check() { [[ "$(/usr/bin/curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT$1")" == "200" ]] && echo "  ✓ $1" || { echo "  ✗ $1" >&2; exit 1; } }
check /readyz
check /
check /login/
check /ask/

TOKEN=$(/usr/bin/curl -s -D - -o /dev/null -X POST "http://127.0.0.1:$PORT/auth/register" \
  -H 'Content-Type: application/json' \
  -d '{"email":"smoke@secondbrain.dev","password":"smoke-password-1","display_name":"Smoke"}' \
  | /usr/bin/grep -i '^set-cookie' | /usr/bin/sed 's/^[Ss]et-[Cc]ookie: sb_session=\([^;]*\).*/\1/')
[[ -n "$TOKEN" ]] || { echo "✗ register did not set a session cookie" >&2; exit 1; }
echo "  ✓ register + session"

printf 'Smoke test fixture: deterministic content for the ingestion pipeline.\n' > "$WORK/fixture.txt"
/usr/bin/curl -sf -H "Cookie: sb_session=$TOKEN" -F "files=@$WORK/fixture.txt" \
  "http://127.0.0.1:$PORT/inbox/upload" > /dev/null
echo "  ✓ upload accepted"

STATUS=""
for i in $(seq 1 30); do
  STATUS=$(/usr/bin/curl -sf -H "Cookie: sb_session=$TOKEN" "http://127.0.0.1:$PORT/documents" \
    | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["status"])')
  [[ "$STATUS" == "processed" || "$STATUS" == "failed" ]] && break
  sleep 1
done
[[ "$STATUS" == "processed" ]] || { echo "✗ document status: $STATUS" >&2; exit 1; }
echo "  ✓ ingestion processed"

kill "$BACKEND_PID"; wait "$BACKEND_PID" 2>/dev/null || true
sleep 1
if /usr/bin/pgrep -f "postgres -D $WORK" >/dev/null 2>&1; then
  echo "✗ embedded postgres survived backend shutdown" >&2; exit 1
fi
echo "  ✓ clean shutdown"

echo "✓ smoke passed (workdir removed)"
