"""Final encode step — encodes the assembled video with h264_videotoolbox (macOS HW encoder)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..utils.ffmpeg import ffmpeg_bin, probe_video_info
from ..utils.ffmpeg import run as run_ffmpeg
from ..utils.json_output import emit_progress

logger = logging.getLogger(__name__)


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Encode the assembled video to the final output file.

    Uses h264_videotoolbox (macOS hardware encoder) for fast, high-quality encoding.
    Falls back to libx264 if VideoToolbox is not available (e.g., non-Apple hardware).

    Args:
        context: Pipeline state. Reads:
            - "assembled_video": Path to the assembled/processed video
            - "output_video": Final output path (set by pipeline orchestrator)
            - "input_video": Used to derive output path if "output_video" not set
        config: Full pipeline config. Reads config["encoding"].

    Returns:
        {"output_video": str} — path to the final encoded output file.
    """
    emit_progress("encode", "encode", 0.0, "Starting final encode...")

    assembled = Path(context["assembled_video"])
    enc_cfg = config.get("encoding", {})

    # Determine output path
    output_path = _get_output_path(context)

    codec = enc_cfg.get("codec", "h264_videotoolbox")
    quality = enc_cfg.get("quality", 65)
    audio_codec = enc_cfg.get("audio_codec", "aac")
    audio_bitrate = enc_cfg.get("audio_bitrate", "192k")

    # Probe input bitrate for VideoToolbox bitrate-based encoding
    input_bitrate_kbps = _probe_video_bitrate_kbps(str(assembled))

    emit_progress("encode", "encode", 0.1, f"Encoding with {codec} (quality={quality})...")

    cmd = _build_encode_cmd(
        input_path=str(assembled),
        output_path=str(output_path),
        codec=codec,
        quality=quality,
        audio_codec=audio_codec,
        audio_bitrate=audio_bitrate,
        input_bitrate_kbps=input_bitrate_kbps,
    )

    try:
        run_ffmpeg(cmd)
    except Exception as exc:
        if "videotoolbox" in codec:
            logger.warning(
                "VideoToolbox encoding failed (%s) — falling back to libx264.", exc
            )
            emit_progress("encode", "encode", 0.1, "VideoToolbox unavailable — falling back to libx264...")
            cmd = _build_encode_cmd(
                input_path=str(assembled),
                output_path=str(output_path),
                codec="libx264",
                quality=quality,
                audio_codec=audio_codec,
                audio_bitrate=audio_bitrate,
                use_crf=True,
            )
            run_ffmpeg(cmd)
        else:
            raise

    emit_progress("encode", "encode", 1.0, f"Encode complete: {output_path.name}")
    return {"output_video": str(output_path)}


def _probe_video_bitrate_kbps(video_path: str) -> int:
    """Probe the video stream bitrate in kbps. Returns a sensible default if unavailable."""
    try:
        info = probe_video_info(video_path)
        streams = info.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        if video_stream:
            # Try stream-level bitrate first, fall back to container bitrate
            bit_rate = video_stream.get("bit_rate") or info.get("format", {}).get("bit_rate")
            if bit_rate:
                return max(1000, int(int(bit_rate) / 1000))
    except Exception:
        pass
    # Safe default: 8 Mbps (good for 1080p)
    return 8000


def _get_output_path(context: dict[str, Any]) -> Path:
    """Determine the final output path from context."""
    if context.get("output_video"):
        return Path(context["output_video"])

    # Derive from input video: /path/to/video.mp4 → /path/to/video_edited.mp4
    input_video = Path(context.get("input_video", "output.mp4"))
    return input_video.parent / f"{input_video.stem}_edited{input_video.suffix}"


def _build_encode_cmd(
    input_path: str,
    output_path: str,
    codec: str,
    quality: int,
    audio_codec: str,
    audio_bitrate: str,
    use_crf: bool = False,
    input_bitrate_kbps: int = 8000,
) -> list[str]:
    """Build the FFmpeg encode command.

    For h264_videotoolbox: uses -b:v (bitrate-based) because VideoToolbox does
    not support -q:v quality scale. Target bitrate is derived from the input video's
    bitrate, scaled by the quality parameter (quality=65 → 65% of input bitrate).
    For libx264 fallback: uses -crf (0-51, lower=better; quality maps to ~18-28 range).
    """
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i", input_path,
        "-vcodec", codec,
    ]

    if use_crf:
        # Map quality (0-100) to CRF scale (18-28)
        # quality=65 → crf=22 (roughly center of good quality range)
        crf = int(18 + (100 - quality) / 100 * 10)
        crf = max(16, min(28, crf))
        cmd += ["-crf", str(crf), "-preset", "medium"]
    else:
        # VideoToolbox requires bitrate-based encoding (-b:v), not -q:v.
        # Scale the input bitrate by quality/100 to get target bitrate.
        target_kbps = max(1000, int(input_bitrate_kbps * quality / 100))
        cmd += ["-b:v", f"{target_kbps}k"]

    cmd += [
        "-acodec", audio_codec,
        "-b:a", audio_bitrate,
        "-movflags", "+faststart",  # optimize MP4 for web playback (moov atom first)
        output_path,
    ]

    return cmd
