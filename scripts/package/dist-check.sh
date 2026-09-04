#!/usr/bin/env bash
# End-to-end gate for the packaged app: cold boot the assembled SecondBrain.app
# with an isolated app-support dir, exercise the real product paths, quit,
# relaunch, and assert persistence. AI is exercised when the machine has an
# HF model cache (SKIP_AI=1 to skip).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP_BIN="$ROOT/dist/SecondBrain.app/Contents/MacOS/SecondBrain"
WORK="$(mktemp -d /tmp/sb-distcheck.XXXXXX)"
SUPPORT="$WORK/app-support"

[[ -x "$APP_BIN" ]] || { echo "✗ $APP_BIN not built — run scripts/package/build-app.sh" >&2; exit 1; }

APP_PID=""
cleanup() {
  [[ -n "$APP_PID" ]] && kill "$APP_PID" 2>/dev/null || true
  [[ -n "$APP_PID" ]] && wait "$APP_PID" 2>/dev/null || true
}
trap cleanup EXIT

launch() {
  SECONDBRAIN_APP_SUPPORT="$SUPPORT" "$APP_BIN" >/dev/null 2>&1 &
  APP_PID=$!
}

wait_for_api() {
  local port=""
  for _ in $(seq 1 120); do
    port=$(/usr/bin/grep -o 'Uvicorn running on http://127.0.0.1:[0-9]*' "$SUPPORT/logs/backend.log" 2>/dev/null | /usr/bin/tail -1 | /usr/bin/grep -o '[0-9]*$' || true)
    [[ -n "$port" ]] && /usr/bin/curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$port/healthz" && { echo "$port"; return 0; }
    kill -0 "$APP_PID" 2>/dev/null || { echo "✗ app exited during startup" >&2; exit 1; }
    sleep 0.5
  done
  echo "✗ backend never became healthy (logs: $SUPPORT/logs)" >&2; exit 1
}

auth_token() {
  local token
  token=$(/usr/bin/curl -s -D - -o /dev/null -X POST "http://127.0.0.1:$1/auth/register" \
    -H 'Content-Type: application/json' \
    -d '{"email":"dist-check@secondbrain.dev","password":"dist-check-password-1","display_name":"Dist Check"}' \
    | /usr/bin/grep -i '^set-cookie' | /usr/bin/sed 's/^[Ss]et-[Cc]ookie: sb_session=\([^;]*\).*/\1/')
  if [[ -z "$token" ]]; then
    token=$(/usr/bin/curl -s -D - -o /dev/null -X POST "http://127.0.0.1:$1/auth/login" \
      -H 'Content-Type: application/json' \
      -d '{"email":"dist-check@secondbrain.dev","password":"dist-check-password-1"}' \
      | /usr/bin/grep -i '^set-cookie' | /usr/bin/sed 's/^[Ss]et-[Cc]ookie: sb_session=\([^;]*\).*/\1/')
  fi
  echo "$token"
}

echo "→ cold boot"
launch
PORT="$(wait_for_api)"
echo "  ✓ api ready on :$PORT"

check() { [[ "$(/usr/bin/curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT$1")" == "200" ]] && echo "  ✓ $1" || { echo "  ✗ $1" >&2; exit 1; } }
check /readyz
check /
check /login/
check /setup/

TOKEN="$(auth_token "$PORT")"
[[ -n "$TOKEN" ]] || { echo "  ✗ register/session" >&2; exit 1; }
echo "  ✓ register + session"

AI_STATUS=$(/usr/bin/curl -s -H "Cookie: sb_session=$TOKEN" "http://127.0.0.1:$PORT/ai/status")
[[ "$AI_STATUS" == *'"available":true'* ]] && echo "  ✓ guided AI available" || echo "  ! guided AI NOT available: $AI_STATUS"

if [[ "${SKIP_AI:-0}" != "1" && -d "$HOME/.cache/huggingface/hub" ]]; then
  echo "→ AI install (seeded from local HF cache)"
  mkdir -p "$SUPPORT/ai/home/models"
  ln -sfn "$HOME/.cache/huggingface/hub" "$SUPPORT/ai/home/models/hub"
  /usr/bin/curl -sf -X POST -H "Cookie: sb_session=$TOKEN" "http://127.0.0.1:$PORT/ai/install" >/dev/null
  for _ in $(seq 1 60); do
    S=$(/usr/bin/curl -s -H "Cookie: sb_session=$TOKEN" "http://127.0.0.1:$PORT/ai/status")
    case "$S" in *'"server_online":true'*) break;; esac
    case "$S" in *'"phase":"error"'*) echo "  ✗ AI install: $S" >&2; exit 1;; esac
    sleep 10
  done
  [[ "$(/usr/bin/curl -s -H "Cookie: sb_session=$TOKEN" "http://127.0.0.1:$PORT/ai/status")" == *'"server_online":true'* ]] \
    && echo "  ✓ AI server online" || { echo "  ✗ AI server never came online" >&2; exit 1; }

  printf 'Dist check fixture: the packaging pipeline works end to end.\n' > "$WORK/fixture.txt"
  /usr/bin/curl -sf -H "Cookie: sb_session=$TOKEN" -F "files=@$WORK/fixture.txt" "http://127.0.0.1:$PORT/inbox/upload" >/dev/null
  STATUS=""
  for _ in $(seq 1 30); do
    STATUS=$(/usr/bin/curl -sf -H "Cookie: sb_session=$TOKEN" "http://127.0.0.1:$PORT/documents" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["status"])')
    [[ "$STATUS" == "processed" || "$STATUS" == "failed" ]] && break
    sleep 2
  done
  [[ "$STATUS" == "processed" ]] && echo "  ✓ AI ingestion processed" || { echo "  ✗ ingestion: $STATUS" >&2; exit 1; }
fi

echo "→ quit + verify clean shutdown"
kill "$APP_PID"; wait "$APP_PID" 2>/dev/null || true; APP_PID=""
sleep 2
if /usr/bin/pgrep -f "secondbrain-backend" >/dev/null 2>&1; then echo "  ✗ backend survived quit" >&2; exit 1; fi
if /usr/bin/pgrep -f "postgres -D $SUPPORT" >/dev/null 2>&1; then echo "  ✗ postgres survived quit" >&2; exit 1; fi
echo "  ✓ children stopped"

echo "→ warm relaunch (persistence)"
launch
PORT="$(wait_for_api)"
TOKEN="$(auth_token "$PORT")"
COUNT=$(/usr/bin/curl -sf -H "Cookie: sb_session=$TOKEN" "http://127.0.0.1:$PORT/documents" | /usr/bin/python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
kill "$APP_PID"; wait "$APP_PID" 2>/dev/null || true; APP_PID=""
[[ "$COUNT" -ge 1 ]] && echo "  ✓ data persisted ($COUNT document(s))" || { echo "  ✗ data lost" >&2; exit 1; }

rm -rf "$WORK"
echo "✓ dist-check passed"
