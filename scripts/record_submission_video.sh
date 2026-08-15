#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DISPLAY_VALUE="${DECISIONVAULT_RECORD_DISPLAY:-:97}"
CDP_PORT="${DECISIONVAULT_RECORD_CDP_PORT:-9267}"
TIMING_SCALE="${DECISIONVAULT_RECORD_TIMING_SCALE:-1}"
OUTPUT="${DECISIONVAULT_RECORD_OUTPUT:-$ROOT/recordings/DecisionVault_Submission_Demo_2m45s.mp4}"
TMP_OUTPUT="${OUTPUT%.mp4}.partial.mp4"
TOKEN_FILE="${DECISIONVAULT_DEMO_TOKEN_FILE:-$ROOT/.venv/demo-token}"
FFPROBE="${DECISIONVAULT_FFPROBE:-/home/bili-guo/miniconda3/envs/aide/bin/ffprobe}"

XVFB_PID=""
RECORDER_PID=""
BROWSER_PID=""

cleanup() {
  set +e
  if [[ -n "$RECORDER_PID" ]] && kill -0 "$RECORDER_PID" 2>/dev/null; then
    kill -INT "$RECORDER_PID" 2>/dev/null
    wait "$RECORDER_PID" 2>/dev/null
  fi
  if [[ -n "$BROWSER_PID" ]] && kill -0 "$BROWSER_PID" 2>/dev/null; then
    kill "$BROWSER_PID" 2>/dev/null
    wait "$BROWSER_PID" 2>/dev/null
  fi
  if [[ -n "$XVFB_PID" ]] && kill -0 "$XVFB_PID" 2>/dev/null; then
    kill "$XVFB_PID" 2>/dev/null
    wait "$XVFB_PID" 2>/dev/null
  fi
}
trap cleanup EXIT INT TERM

for tool in Xvfb google-chrome gst-launch-1.0 gst-inspect-1.0; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERROR: required tool not found: $tool" >&2
    exit 2
  fi
done

if [[ ! -x "$FFPROBE" ]]; then
  echo "ERROR: ffprobe not found at configured path" >&2
  exit 2
fi

for plugin in ximagesrc x264enc h264parse mp4mux videoconvert queue; do
  if ! gst-inspect-1.0 "$plugin" >/dev/null 2>&1; then
    echo "ERROR: required GStreamer plugin not found: $plugin" >&2
    exit 2
  fi
done

if [[ ! -s "$TOKEN_FILE" ]]; then
  echo "ERROR: demo token file is unavailable" >&2
  exit 2
fi

mkdir -p "$(dirname "$OUTPUT")"
rm -f "$TMP_OUTPUT"

echo "Starting isolated 1920x1080 recording display"
Xvfb "$DISPLAY_VALUE" -screen 0 1920x1080x24 -nolisten tcp -ac \
  >"/tmp/decisionvault-record-xvfb.log" 2>&1 &
XVFB_PID=$!
sleep 0.8
if ! kill -0 "$XVFB_PID" 2>/dev/null; then
  echo "ERROR: Xvfb failed to start" >&2
  exit 2
fi

echo "Starting Chrome kiosk on hosted DecisionVault"
DISPLAY="$DISPLAY_VALUE" \
DECISIONVAULT_DEMO_DISPLAY="$DISPLAY_VALUE" \
DECISIONVAULT_DEMO_CDP_PORT="$CDP_PORT" \
bash scripts/start_submission_browser.sh >/tmp/decisionvault-record-browser-start.log 2>&1

BROWSER_PID_FILE="/tmp/decisionvault-demo-browser-${CDP_PORT}.pid"
if [[ ! -s "$BROWSER_PID_FILE" ]]; then
  echo "ERROR: Chrome PID file was not created" >&2
  exit 2
fi
BROWSER_PID="$(cat "$BROWSER_PID_FILE")"

for _ in $(seq 1 80); do
  if curl -fsS "http://127.0.0.1:${CDP_PORT}/json/version" >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
if ! curl -fsS "http://127.0.0.1:${CDP_PORT}/json/version" >/dev/null 2>&1; then
  echo "ERROR: Chrome CDP did not become ready" >&2
  exit 2
fi

echo "Starting H.264 screen capture"
DISPLAY="$DISPLAY_VALUE" gst-launch-1.0 -q -e \
  ximagesrc display-name="$DISPLAY_VALUE" use-damage=false show-pointer=true \
  ! video/x-raw,framerate=30/1,width=1920,height=1080 \
  ! videoconvert \
  ! video/x-raw,format=I420 \
  ! queue \
  ! x264enc bitrate=8000 speed-preset=veryfast tune=zerolatency key-int-max=60 \
  ! h264parse \
  ! mp4mux faststart=true \
  ! filesink location="$TMP_OUTPUT" \
  >/tmp/decisionvault-record-gstreamer.log 2>&1 &
RECORDER_PID=$!
sleep 1.0
if ! kill -0 "$RECORDER_PID" 2>/dev/null; then
  echo "ERROR: GStreamer recorder failed to start" >&2
  exit 2
fi

echo "Running frozen 2:45 browser automation"
set +e
DISPLAY="$DISPLAY_VALUE" \
DECISIONVAULT_DEMO_DISPLAY="$DISPLAY_VALUE" \
DECISIONVAULT_DEMO_CDP_PORT="$CDP_PORT" \
DECISIONVAULT_DEMO_TOKEN_FILE="$TOKEN_FILE" \
DECISIONVAULT_DEMO_TIMING_SCALE="$TIMING_SCALE" \
python3 scripts/run_submission_demo.py
DEMO_RC=$?
set -e

sleep 0.7
kill -INT "$RECORDER_PID" 2>/dev/null || true
wait "$RECORDER_PID" || true
RECORDER_PID=""

if [[ "$DEMO_RC" -ne 0 ]]; then
  echo "ERROR: browser automation failed; partial recording retained at $TMP_OUTPUT" >&2
  exit "$DEMO_RC"
fi

if [[ ! -s "$TMP_OUTPUT" ]]; then
  echo "ERROR: recorder produced no MP4" >&2
  exit 2
fi

read -r CODEC WIDTH HEIGHT PIX_FMT FPS DURATION < <(
  {
    "$FFPROBE" -v error \
      -select_streams v:0 \
      -show_entries stream=codec_name,width,height,pix_fmt,avg_frame_rate:format=duration \
      -of default=noprint_wrappers=1:nokey=1 \
      "$TMP_OUTPUT" | tr '\n' ' '
    echo
  }
)

echo "Video probe: codec=$CODEC size=${WIDTH}x${HEIGHT} pix_fmt=$PIX_FMT fps=$FPS duration=${DURATION}s"

if [[ "$CODEC" != "h264" || "$WIDTH" != "1920" || "$HEIGHT" != "1080" || "$PIX_FMT" != "yuv420p" ]]; then
  echo "ERROR: video format gate failed" >&2
  exit 2
fi

python3 - "$FPS" "$DURATION" "$TIMING_SCALE" <<'PY'
from fractions import Fraction
import sys

fps = float(Fraction(sys.argv[1]))
duration = float(sys.argv[2])
scale = float(sys.argv[3])

if abs(fps - 30.0) > 0.05:
    raise SystemExit(f"ERROR: expected 30fps, got {fps}")

if scale >= 0.99:
    if not (160.0 <= duration < 180.0):
        raise SystemExit(f"ERROR: formal recording duration outside 2:40-3:00 gate: {duration:.3f}s")
else:
    if duration <= 1.0:
        raise SystemExit(f"ERROR: compressed recording is unexpectedly short: {duration:.3f}s")
PY

mv -f "$TMP_OUTPUT" "$OUTPUT"
echo "PASS: formal submission capture created"
echo "output=$OUTPUT"

