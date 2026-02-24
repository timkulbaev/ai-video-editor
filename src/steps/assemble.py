"""Assembly step — cuts video to kept segments and concatenates them via FFmpeg."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils.ffmpeg import ffmpeg_bin
from ..utils.ffmpeg import run as run_ffmpeg
from ..utils.json_output import emit_progress


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Cut video to kept segments and concatenate them into a single intermediate file.

    Uses FFmpeg's concat demuxer approach:
    1. Extract each segment to a temp file using output-side seek + re-encode (frame-accurate)
    2. Write a concat manifest listing all segments
    3. Join with `ffmpeg -f concat -safe 0 -i list.txt -c copy`

    This is more memory-efficient than filter_complex for videos with many segments.

    Args:
        context: Pipeline state. Reads:
            - "input_video": Path to original video
            - "keep_segments": list of (start_sec, end_sec) tuples to keep
            - "work_dir": Path to temporary working directory
        config: Full pipeline config (unused by this step, included for interface consistency).

    Returns:
        {"assembled_video": str} — path to the assembled intermediate video.
    """
    emit_progress("assembly", "assemble", 0.0, "Assembling kept segments...")

    input_video = str(context["input_video"])
    keep_segments: list[tuple[float, float]] = context.get("keep_segments", [])
    work_dir = Path(context["work_dir"])

    if not keep_segments:
        raise ValueError("assemble step received empty keep_segments — nothing to assemble.")

    segments_dir = work_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)

    # Discard micro-segments too short to contain meaningful content.
    # Filler removal can produce near-zero-duration tail segments; these
    # cause worst-case keyframe overrun and contribute no real frames.
    MIN_DURATION = 0.2  # seconds
    keep_segments = [(s, e) for s, e in keep_segments if (e - s) >= MIN_DURATION]

    if not keep_segments:
        raise ValueError(
            "assemble step: all segments were shorter than the minimum duration "
            f"({MIN_DURATION}s) and were discarded — nothing to assemble."
        )

    segment_files: list[Path] = []
    total = len(keep_segments)

    for i, (start, end) in enumerate(keep_segments):
        seg_path = segments_dir / f"seg_{i:04d}.mp4"
        _extract_segment(input_video, start, end, seg_path)
        segment_files.append(seg_path)
        emit_progress(
            "assembly", "assemble",
            (i + 1) / total * 0.8,
            f"Extracted segment {i + 1}/{total} ({start:.1f}s–{end:.1f}s)",
        )

    # Write concat manifest
    concat_list = work_dir / "concat_list.txt"
    _write_concat_list(concat_list, segment_files)

    output_path = work_dir / "assembled.mp4"
    _concat_segments(concat_list, output_path)

    emit_progress("assembly", "assemble", 1.0, f"Assembly complete: {len(keep_segments)} segments joined.")
    return {"assembled_video": str(output_path)}


def _extract_segment(
    input_video: str,
    start: float,
    end: float,
    output_path: Path,
) -> None:
    """Extract a single video segment using frame-accurate FFmpeg re-encode.

    Uses output-side seek (-ss after -i) and relative duration (-t) instead of
    input-side seek + -to. This forces FFmpeg to decode from the start of the
    stream to the exact requested frame, eliminating keyframe-snapping overlap
    that caused content duplication with -c copy.
    """
    duration = end - start
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i", input_video,
        "-ss", str(start),        # output-side seek — frame-accurate
        "-t", str(duration),      # relative duration (not absolute -to)
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-crf", "18",
        "-c:a", "aac",
        str(output_path),
    ]
    run_ffmpeg(cmd)


def _write_concat_list(list_path: Path, segment_files: list[Path]) -> None:
    """Write the FFmpeg concat demuxer manifest file."""
    lines = []
    for seg in segment_files:
        # Escape single quotes in paths per FFmpeg concat demuxer spec
        escaped = str(seg).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _concat_segments(concat_list: Path, output_path: Path) -> None:
    """Concatenate all segments using FFmpeg's concat demuxer."""
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",             # preserve codec from segments (stream copy)
        str(output_path),
    ]
    run_ffmpeg(cmd)
