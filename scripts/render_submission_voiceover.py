#!/usr/bin/env python3
"""Render the frozen DecisionVault English AI voiceover and mux it with video.

The narration is generated as independent Edge neural-TTS segments so each
section stays aligned with the frozen 2:45 visual timeline.  The screen master
remains untouched; the final artifact is written alongside it as a separate
voiceover MP4.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
VIDEO = Path(
    os.environ.get(
        "DECISIONVAULT_VOICEOVER_VIDEO",
        ROOT / "recordings" / "DecisionVault_Submission_Demo_2m45s.mp4",
    )
)
OUTPUT = Path(
    os.environ.get(
        "DECISIONVAULT_VOICEOVER_OUTPUT",
        ROOT / "recordings" / "DecisionVault_Submission_Demo_2m45s_Voiceover.mp4",
    )
)
WORK = Path(os.environ.get("DECISIONVAULT_VOICEOVER_WORK", ROOT / ".venv" / "voiceover"))
EDGE_TTS_PATH = Path(
    os.environ.get("DECISIONVAULT_EDGE_TTS_PATH", "/home/bili-guo/.cache/bridgesat_edge_tts")
)
FFMPEG = Path(
    os.environ.get("DECISIONVAULT_FFMPEG", "/home/bili-guo/miniconda3/envs/aide/bin/ffmpeg")
)
FFPROBE = Path(
    os.environ.get("DECISIONVAULT_FFPROBE", "/home/bili-guo/miniconda3/envs/aide/bin/ffprobe")
)
VOICE = os.environ.get("DECISIONVAULT_VOICE", "en-US-AndrewNeural")
RATE = os.environ.get("DECISIONVAULT_VOICE_RATE", "+8%")
REUSE_SEGMENTS = os.environ.get("DECISIONVAULT_REUSE_VOICE_SEGMENTS", "0") == "1"
REGENERATE_SEGMENTS = {
    int(value.strip())
    for value in os.environ.get("DECISIONVAULT_REGENERATE_VOICE_SEGMENTS", "").split(",")
    if value.strip()
}


SEGMENTS = [
    (
        0.0,
        18.0,
        "AI agents can remember past information. But production agents need something harder: "
        "memory of what actually worked, and rules for when that memory is safe to trust. "
        "DecisionVault turns long-term agent memory into governed decision evidence.",
    ),
    (
        18.0,
        34.0,
        "CockroachDB is the authoritative memory layer. Distributed Vector Indexing recalls "
        "relevant outcome evidence. Deterministic governance commits the action, AWS Lambda "
        "revalidates execution, and the model only explains the decision. It never controls it.",
    ),
    (
        34.0,
        80.0,
        "Here Agent A records that generic retry failed. Now Agent B receives the same kind of "
        "recovery problem. With memory disabled, it repeats the generic retry. With memory "
        "enabled, CockroachDB recalls Agent A's governed outcome evidence, and Agent B changes "
        "to refresh payment token. The producer is visible here: recovery observer. The agents "
        "did not need to share an in-memory conversation. The behavior changed because of "
        "durable shared memory, and the temporary demo scope is cleaned after the proof. "
        "The comparison is controlled: the problem, policy, and model stay the same. The only "
        "changed variable is whether governed persistent memory is available. That is the "
        "causal proof: durable memory changes the next decision without becoming execution "
        "authority.",
    ),
    (
        80.0,
        108.0,
        "Useful memory also needs a safe failure mode. Here two governed memories conflict. "
        "DecisionVault does not guess. It returns conflict abstain, no strategy, and executable "
        "false. The execution gateway rechecks current policy, so conflicting memory cannot "
        "force a real action. The conflicting memories remain visible for audit instead of "
        "being silently discarded. Abstention is therefore an explicit, reviewable decision.",
    ),
    (
        108.0,
        138.0,
        "DecisionVault also verifies real external side effects with signed execution receipts. "
        "But a transport success is not automatically a business success. A verified external "
        "write remains outcome unknown, so it cannot enter long-term memory or calibration "
        "until independent business evidence proves the real outcome. Memory can influence "
        "execution, but it cannot manufacture its own success label.",
    ),
    (
        138.0,
        158.0,
        "The current build passes two hundred fifty-seven tests and all fourteen production "
        "semantic adversarial cases. The latest thirty-minute hosted soak finished with zero "
        "transport and zero contract-validation failures, and the final database audit found "
        "zero leaked business-memory rows.",
    ),
    (
        158.0,
        165.8,
        "DecisionVault makes agent memory useful enough to change decisions, and governed "
        "enough to trust before execution.",
    ),
]


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    subprocess.run(cmd, cwd=ROOT, env=env, check=True)


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(result.stdout.strip())


def main() -> int:
    if not VIDEO.is_file():
        raise SystemExit(f"screen master not found: {VIDEO}")
    if not EDGE_TTS_PATH.joinpath("edge_tts").is_dir():
        raise SystemExit(f"Edge TTS cache not found: {EDGE_TTS_PATH}")
    for binary in (FFMPEG, FFPROBE):
        if not binary.is_file():
            raise SystemExit(f"required media tool not found: {binary}")

    WORK.mkdir(parents=True, exist_ok=True)
    tts_env = os.environ.copy()
    existing = tts_env.get("PYTHONPATH", "")
    tts_env["PYTHONPATH"] = str(EDGE_TTS_PATH) + (os.pathsep + existing if existing else "")

    media: list[Path] = []
    for index, (start, end, text) in enumerate(SEGMENTS, start=1):
        target = WORK / f"segment_{index:02d}.mp3"
        regenerate = index in REGENERATE_SEGMENTS
        if regenerate or not (REUSE_SEGMENTS and target.is_file() and target.stat().st_size > 0):
            run(
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
                    str(target),
                ],
                env=tts_env,
            )
        duration = probe_duration(target)
        available = end - start
        if duration > available:
            raise SystemExit(
                f"segment {index} is too long: {duration:.3f}s > {available:.3f}s; "
                "increase DECISIONVAULT_VOICE_RATE slightly"
            )
        print(
            f"voice_segment_{index}=PASS start={start:.1f}s slot={available:.1f}s "
            f"audio={duration:.3f}s"
        )
        media.append(target)

    video_duration = probe_duration(VIDEO)
    ffmpeg_cmd = [str(FFMPEG), "-y", "-v", "error", "-i", str(VIDEO)]
    for path in media:
        ffmpeg_cmd.extend(["-i", str(path)])

    filters: list[str] = []
    mix_inputs: list[str] = []
    for index, ((start, _end, _text), _path) in enumerate(zip(SEGMENTS, media), start=1):
        delay = round(start * 1000)
        label = f"a{index}"
        filters.append(
            f"[{index}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"adelay={delay}|{delay}[{label}]"
        )
        mix_inputs.append(f"[{label}]")
    filters.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(media)}:duration=longest:normalize=0,"
        "loudnorm=I=-16:LRA=7:TP=-1.5,"
        f"apad=whole_dur={video_duration:.6f}[voice]"
    )

    temp = OUTPUT.with_suffix(".partial.mp4")
    temp.unlink(missing_ok=True)
    ffmpeg_cmd.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "0:v:0",
            "-map",
            "[voice]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-t",
            f"{video_duration:.6f}",
            "-movflags",
            "+faststart",
            str(temp),
        ]
    )
    run(ffmpeg_cmd)

    output_duration = probe_duration(temp)
    if not (160.0 <= output_duration < 180.0):
        raise SystemExit(f"voiceover output duration gate failed: {output_duration:.3f}s")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(temp, OUTPUT)
    print(f"voiceover_duration={output_duration:.6f}s")
    print(f"voice={VOICE}")
    print(f"PASS: voiceover master created at {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
