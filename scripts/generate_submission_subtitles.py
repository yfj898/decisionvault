#!/usr/bin/env python3
"""Generate a timeline-aligned English SRT for the final DecisionVault demo.

The subtitle timings come from Edge neural TTS word-boundary output using the
same voice, rate, and narration text as the accepted voiceover. Each segment is
then offset onto the frozen 2:45 submission timeline.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

from render_submission_voiceover import EDGE_TTS_PATH, RATE, SEGMENTS, VOICE


ROOT = Path(__file__).resolve().parents[1]
WORK = Path(os.environ.get("DECISIONVAULT_SUBTITLE_WORK", ROOT / ".venv" / "subtitles"))
OUTPUT = Path(
    os.environ.get(
        "DECISIONVAULT_SUBTITLE_OUTPUT",
        WORK / "DecisionVault_Submission_Demo_2m45s_Final.srt",
    )
)

TIMING_RE = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}),(?P<ms>\d{3})"
    r"\s+-->\s+"
    r"(?P<h2>\d{2}):(?P<m2>\d{2}):(?P<s2>\d{2}),(?P<ms2>\d{3})"
)


def _seconds(match: re.Match[str], suffix: str = "") -> float:
    return (
        int(match.group("h" + suffix)) * 3600
        + int(match.group("m" + suffix)) * 60
        + int(match.group("s" + suffix))
        + int(match.group("ms" + suffix)) / 1000
    )


def _stamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _parse_srt(path: Path) -> list[tuple[float, float, str]]:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    result: list[tuple[float, float, str]] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            continue
        match = TIMING_RE.fullmatch(lines[1].strip())
        if not match:
            raise RuntimeError(f"unexpected subtitle timing in {path}: {lines[1]!r}")
        text = " ".join(line.strip() for line in lines[2:] if line.strip())
        result.append((_seconds(match), _seconds(match, "2"), text))
    return result


def main() -> int:
    if not EDGE_TTS_PATH.joinpath("edge_tts").is_dir():
        raise SystemExit(f"Edge TTS cache not found: {EDGE_TTS_PATH}")

    WORK.mkdir(parents=True, exist_ok=True)
    tts_env = os.environ.copy()
    existing = tts_env.get("PYTHONPATH", "")
    tts_env["PYTHONPATH"] = str(EDGE_TTS_PATH) + (os.pathsep + existing if existing else "")

    cues: list[tuple[float, float, str]] = []
    for index, (start, end, text) in enumerate(SEGMENTS, start=1):
        media = WORK / f"timing_{index:02d}.mp3"
        srt = WORK / f"timing_{index:02d}.srt"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "edge_tts",
                "--voice",
                VOICE,
                "--rate",
                RATE,
                "--text",
                text,
                "--write-media",
                str(media),
                "--write-subtitles",
                str(srt),
            ],
            cwd=ROOT,
            env=tts_env,
            check=True,
        )
        local = _parse_srt(srt)
        if not local:
            raise SystemExit(f"segment {index} produced no subtitle cues")
        if local[-1][1] > (end - start) + 0.25:
            raise SystemExit(
                f"segment {index} subtitle timing exceeds visual slot: "
                f"{local[-1][1]:.3f}s > {end-start:.3f}s"
            )
        for cue_start, cue_end, cue_text in local:
            cues.append((start + cue_start, start + cue_end, cue_text))
        print(
            f"subtitle_segment_{index}=PASS cues={len(local)} "
            f"end={start + local[-1][1]:.3f}s"
        )

    lines: list[str] = []
    for index, (start, end, text) in enumerate(cues, start=1):
        lines.extend([str(index), f"{_stamp(start)} --> {_stamp(end)}", text, ""])
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"subtitle_cues={len(cues)}")
    print(f"PASS: subtitle timeline created at {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
