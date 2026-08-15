#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

INPUT="${DECISIONVAULT_SUBTITLE_INPUT:-$ROOT/recordings/DecisionVault_Submission_Demo_2m45s_Final.mp4}"
SRT="${DECISIONVAULT_SUBTITLE_SRT:-$ROOT/.venv/subtitles/DecisionVault_Submission_Demo_2m45s_Final.srt}"
VIDEO_ONLY="${DECISIONVAULT_SUBTITLE_VIDEO_ONLY:-$ROOT/.venv/subtitles/final-subtitled-video.mp4}"
OUTPUT="${DECISIONVAULT_SUBTITLE_OUTPUT_VIDEO:-$ROOT/recordings/DecisionVault_Submission_Demo_2m45s_Final_Subtitled.mp4}"
FFMPEG="${DECISIONVAULT_FFMPEG:-/home/bili-guo/miniconda3/envs/aide/bin/ffmpeg}"
FFPROBE="${DECISIONVAULT_FFPROBE:-/home/bili-guo/miniconda3/envs/aide/bin/ffprobe}"

for tool in gst-launch-1.0 gst-inspect-1.0; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "ERROR: required tool not found: $tool" >&2
    exit 2
  }
done

for plugin in qtdemux h264parse avdec_h264 videoconvert textoverlay subparse x264enc mp4mux; do
  gst-inspect-1.0 "$plugin" >/dev/null 2>&1 || {
    echo "ERROR: required GStreamer plugin not found: $plugin" >&2
    exit 2
  }
done

[[ -s "$INPUT" ]] || { echo "ERROR: input video unavailable" >&2; exit 2; }
[[ -s "$SRT" ]] || { echo "ERROR: subtitle file unavailable" >&2; exit 2; }
[[ -x "$FFMPEG" && -x "$FFPROBE" ]] || {
  echo "ERROR: ffmpeg/ffprobe unavailable" >&2
  exit 2
}

mkdir -p "$(dirname "$VIDEO_ONLY")" "$(dirname "$OUTPUT")"
rm -f "$VIDEO_ONLY" "$OUTPUT"

echo "Rendering hard-subtitled video track"
gst-launch-1.0 -q -e \
  filesrc location="$INPUT" ! qtdemux name=demux \
  demux.video_0 ! queue ! h264parse ! avdec_h264 ! videoconvert ! sub.video_sink \
  filesrc location="$SRT" ! subparse ! sub.text_sink \
  textoverlay name=sub \
    wait-text=false \
    auto-resize=false \
    font-desc="Noto Sans 24" \
    shaded-background=true \
    shading-value=90 \
    valignment=bottom \
    halignment=center \
    line-alignment=center \
    draw-outline=true \
    draw-shadow=true \
    deltay=-20 \
  sub. ! videoconvert ! video/x-raw,format=I420 \
  ! x264enc bitrate=8000 speed-preset=veryfast key-int-max=60 \
  ! h264parse ! video/x-h264,profile=high \
  ! mp4mux faststart=true ! filesink location="$VIDEO_ONLY"

echo "Muxing original AAC narration without re-encoding"
"$FFMPEG" -y -v error \
  -i "$VIDEO_ONLY" \
  -i "$INPUT" \
  -map 0:v:0 \
  -map 1:a:0 \
  -c copy \
  -shortest \
  -movflags +faststart \
  "$OUTPUT"

python3 - "$FFPROBE" "$OUTPUT" <<'PY'
import json
import subprocess
import sys

ffprobe, output = sys.argv[1:]
probe = subprocess.run(
    [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_name,profile,pix_fmt,width,height,r_frame_rate,sample_rate,channels:format=duration",
        "-of",
        "json",
        output,
    ],
    check=True,
    text=True,
    capture_output=True,
)
data = json.loads(probe.stdout)
video = next(s for s in data["streams"] if s.get("codec_name") == "h264")
audio = next(s for s in data["streams"] if s.get("codec_name") == "aac")
duration = float(data["format"]["duration"])

print(
    "Subtitle export probe: "
    f"video={video['codec_name']}/{video.get('profile')}/{video.get('pix_fmt')} "
    f"{video.get('width')}x{video.get('height')} fps={video.get('r_frame_rate')} "
    f"audio={audio['codec_name']} {audio.get('sample_rate')}Hz ch={audio.get('channels')} "
    f"duration={duration:.6f}s"
)

if video.get("profile") != "High" or video.get("pix_fmt") != "yuv420p":
    raise SystemExit("ERROR: final subtitled video codec/profile/pixel-format gate failed")
if (video.get("width"), video.get("height")) != (1920, 1080):
    raise SystemExit("ERROR: final subtitled resolution gate failed")
if audio.get("sample_rate") != "48000" or audio.get("channels") != 2:
    raise SystemExit("ERROR: final subtitled audio gate failed")
if not (160.0 <= duration < 180.0):
    raise SystemExit(f"ERROR: final subtitled duration gate failed: {duration:.3f}s")
PY

echo "PASS: hard-subtitled submission video created"
echo "output=$OUTPUT"
