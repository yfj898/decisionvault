#!/usr/bin/env bash
set -euo pipefail

URL="${DECISIONVAULT_DEMO_URL:-https://mfcr7b2k3j7lrwr44u35i5rchq0fbncb.lambda-url.ap-northeast-1.on.aws/}"
PORT="${DECISIONVAULT_DEMO_CDP_PORT:-9257}"
DISPLAY_VALUE="${DECISIONVAULT_DEMO_DISPLAY:-${DISPLAY:-:1}}"
PROFILE="${DECISIONVAULT_DEMO_PROFILE:-/tmp/decisionvault-submission-demo-$(date +%Y%m%d-%H%M%S)}"

if command -v google-chrome >/dev/null 2>&1; then
  CHROME="$(command -v google-chrome)"
elif command -v google-chrome-stable >/dev/null 2>&1; then
  CHROME="$(command -v google-chrome-stable)"
else
  echo "ERROR: Google Chrome is required for the frozen submission browser." >&2
  exit 1
fi

if ! curl -fsS --max-time 10 "${URL%/}/health" >/dev/null 2>&1; then
  echo "ERROR: DecisionVault live health endpoint is not reachable: ${URL%/}/health" >&2
  exit 1
fi

if curl -fsS "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "ERROR: CDP port ${PORT} is already in use." >&2
  exit 1
fi

mkdir -p "$PROFILE"

echo "Starting DecisionVault submission browser"
echo "  URL:     $URL"
echo "  DISPLAY: $DISPLAY_VALUE"
echo "  CDP:     $PORT"
echo "  PROFILE: $PROFILE"

DISPLAY="$DISPLAY_VALUE" "$CHROME" \
  --kiosk \
  --no-first-run \
  --no-default-browser-check \
  --disable-session-crashed-bubble \
  --disable-infobars \
  --remote-allow-origins='*' \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE" \
  --window-position=0,0 \
  --window-size=1920,1080 \
  "$URL" \
  >"/tmp/decisionvault-demo-browser-${PORT}.log" 2>&1 &

PID=$!
echo "$PID" > "/tmp/decisionvault-demo-browser-${PORT}.pid"
echo "$PROFILE" > "/tmp/decisionvault-demo-browser-${PORT}.profile"

for _ in $(seq 1 100); do
  if curl -fsS "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done

if ! curl -fsS "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
  echo "ERROR: Chrome started but CDP did not become ready." >&2
  exit 1
fi

echo
echo "READY"
echo "1. Confirm the browser fills the 1920x1080 recording canvas."
echo "2. Start Ubuntu/OBS screen recording."
echo "3. Run from the DecisionVault repo:"
echo "   python3 scripts/run_submission_demo.py"
echo
echo "The automation reads .venv/demo-token without printing it."
echo "Browser PID: $PID"
