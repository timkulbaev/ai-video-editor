"""Extract audio as WAV from video via FFmpeg."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils.ffmpeg import ffmpeg_bin, run as run_ffmpeg
from ..utils.json_output import emit_progress


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Extract audio track from video as a 16kHz mono WAV file.

    16kHz mono is the ideal format for both Silero VAD and Whisper.

    Args:
        context: Pipeline state. Reads:
            - "input_video": Path to the input video file
            - "work_dir": Temporary working directory
        config: Full pipeline config (unused by this step).

    Returns:
        {"audio_wav": str} — path to the extracted WAV file.
    """
    emit_progress("analysis", "extract_audio", 0.0, "Extracting audio from video...")

    video_path = Path(context["input_video"])
    work_dir = Path(context["work_dir"])
    work_dir.mkdir(parents=True, exist_ok=True)

    wav_path = work_dir / f"{video_path.stem}_audio.wav"

    cmd = [
        ffmpeg_bin(),
        "-y",                    # overwrite output
        "-i", str(video_path),
        "-vn",                   # no video stream
        "-acodec", "pcm_s16le",  # 16-bit PCM
        "-ar", "16000",          # 16 kHz (optimal for VAD + Whisper)
        "-ac", "1",              # mono
        str(wav_path),
    ]

    run_ffmpeg(cmd)

    emit_progress("analysis", "extract_audio", 1.0, f"Audio extracted: {wav_path.name}")
    return {"audio_wav": str(wav_path)}
