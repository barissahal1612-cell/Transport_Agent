#!/usr/bin/env bash
# Local dev check: start `agentcore dev` headless, invoke it once, clean up.
# Uses port 8081 (or 8082 if 8081 is busy). Never uses or stops port 8080.
set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${LOCAL_DEV_PORT:-8081}"
PAYLOAD='{"prompt":"Merhaba"}'
LOG_FILE="$(mktemp -t agentcore-dev.XXXXXX.log)"
DEV_PID=""

port_busy() { ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]$1$"; }

if [ "$PORT" = "8080" ]; then
  echo "Refusing to use port 8080 (reserved by the IDE)." >&2
  exit 2
fi
if port_busy "$PORT"; then
  echo "Port $PORT busy, falling back to 8082."
  PORT=8082
fi
if [ "$PORT" = "8080" ] || port_busy "$PORT"; then
  echo "Port $PORT unavailable." >&2
  exit 2
fi

cleanup() {
  if [ -n "$DEV_PID" ] && kill -0 "$DEV_PID" 2>/dev/null; then
    # Stop only the process group we started.
    kill -- -"$DEV_PID" 2>/dev/null || kill "$DEV_PID" 2>/dev/null
    sleep 1
    kill -9 -- -"$DEV_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "$PROJECT_DIR" || exit 1
setsid agentcore dev --port "$PORT" >"$LOG_FILE" 2>&1 &
DEV_PID=$!
echo "Started agentcore dev (pid $DEV_PID) on port $PORT; log: $LOG_FILE"

for _ in $(seq 1 60); do
  if port_busy "$PORT"; then READY=1; break; fi
  kill -0 "$DEV_PID" 2>/dev/null || { echo "dev server exited early:" >&2; tail -n 30 "$LOG_FILE" >&2; exit 1; }
  sleep 2
done
if [ "${READY:-0}" != 1 ]; then
  echo "dev server not ready in time:" >&2; tail -n 30 "$LOG_FILE" >&2; exit 1
fi

echo "--- invoke ---"
agentcore invoke --runtime agent --local --port "$PORT" --payload "$PAYLOAD"
RC=$?
echo
echo "--- invoke exit code: $RC ---"
exit "$RC"
