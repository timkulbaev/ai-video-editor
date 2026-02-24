"""Audio enhancement step — applies FFmpeg filter chain to improve audio quality."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils.ffmpeg import ffmpeg_bin
from ..utils.ffmpeg import run as run_ffmpeg
from ..utils.json_output import emit_progress


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Apply the full audio enhancement filter chain to the assembled video.

    Reads context["assembled_video"], applies the audio filter chain in-place
    (re-encodes audio stream only), and writes to a new file.

    Args:
        context: Pipeline state. Reads:
            - "assembled_video": Path to assembled video file
            - "work_dir": Path to temporary working directory
        config: Full pipeline config. Reads config["audio"].

    Returns:
        {"assembled_video": Path} — updated path pointing to the enhanced video.
    """
    audio_cfg = config.get("audio", {})

    if not audio_cfg.get("enabled", True):
        emit_progress("assembly", "enhance_audio", 1.0, "Audio enhancement disabled — skipping.")
        return {}

    emit_progress("assembly", "enhance_audio", 0.0, "Applying audio enhancement chain...")

    assembled = Path(context["assembled_video"])
    work_dir = Path(context["work_dir"])
    output_path = work_dir / f"{assembled.stem}_audio_enhanced{assembled.suffix}"

    filter_chain = _build_filter_chain(audio_cfg)

    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i", str(assembled),
        "-vcodec", "copy",       # copy video stream unchanged
        "-af", filter_chain,
        "-acodec", "aac",
        "-b:a", "192k",
        str(output_path),
    ]

    emit_progress("assembly", "enhance_audio", 0.3, "Running FFmpeg audio filter chain...")
    run_ffmpeg(cmd)

    emit_progress("assembly", "enhance_audio", 1.0, "Audio enhancement complete.")
    return {"assembled_video": str(output_path)}


def _build_filter_chain(audio_cfg: dict[str, Any]) -> str:
    """Build the FFmpeg audio filter string from config values.

    The chain applies in order:
      1. afftdn  — adaptive FFT noise reduction
      2. highpass — remove low-frequency rumble
      3. equalizer — static de-essing at ~6 kHz
      4. acompressor — dynamic range compression
      5. alimiter — peak limiter to prevent clipping
      6. loudnorm — EBU R128 loudness normalization to -14 LUFS
    """
    denoise_level = audio_cfg.get("denoise_level", -25)
    highpass_freq = audio_cfg.get("highpass_freq", 80)
    deess_freq = audio_cfg.get("deess_freq", 6000)
    deess_gain = audio_cfg.get("deess_gain", -4)
    comp_threshold = audio_cfg.get("compressor_threshold", -18)
    comp_ratio = audio_cfg.get("compressor_ratio", 3)
    limiter_limit = audio_cfg.get("limiter_limit", -1)
    loudness_target = audio_cfg.get("loudness_target", -14)

    filters = []

    if audio_cfg.get("denoise", True):
        filters.append(f"afftdn=nf={denoise_level}")

    filters.append(f"highpass=f={highpass_freq}")
    filters.append(
        f"equalizer=f={deess_freq}:t=q:w=2:g={deess_gain}"
    )
    filters.append(
        f"acompressor=threshold={comp_threshold}dB:ratio={comp_ratio}:attack=5:release=50"
    )
    filters.append(f"alimiter=limit={limiter_limit}dB")
    filters.append(
        f"loudnorm=I={loudness_target}:LRA=11:TP=-1"
    )

    return ",".join(filters)
