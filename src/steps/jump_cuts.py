"""Jump cuts step — alternating zoom punch-in with optional face-based position smoothing."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..utils.ffmpeg import ffmpeg_bin, probe_video_info
from ..utils.ffmpeg import run as run_ffmpeg
from ..utils.face_detect import sample_face_positions, average_face_position
from ..utils.json_output import emit_progress

logger = logging.getLogger(__name__)


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Apply alternating zoom punch-in at cut points with optional face-centering.

    Even-indexed segments: 100% (no zoom).
    Odd-indexed segments: zoom_factor% zoom (crop + scale back).

    If config["video"]["position_smoothing"]["enabled"] is True, the crop offset
    is computed from the speaker's median face position in that segment (via MediaPipe).
    Falls back to center crop if no face is detected.

    Args:
        context: Pipeline state. Reads:
            - "assembled_video": Path to assembled video
            - "keep_segments": list of (start_sec, end_sec) tuples (used for face sampling)
            - "work_dir": Path to temporary working directory
        config: Full pipeline config. Reads config["video"]["zoom_punch"] and
                config["video"]["position_smoothing"].

    Returns:
        {"assembled_video": str} — path to the zoom-processed video.
        Returns empty dict if zoom punch is disabled.
    """
    video_cfg = config.get("video", {})
    zoom_cfg = video_cfg.get("zoom_punch", {})
    smoothing_cfg = video_cfg.get("position_smoothing", {})

    if not zoom_cfg.get("enabled", True):
        emit_progress("assembly", "jump_cuts", 1.0, "Jump cut zoom disabled — skipping.")
        return {}

    zoom_factor: float = zoom_cfg.get("zoom_factor", 1.05)
    face_smooth: bool = smoothing_cfg.get("enabled", True)

    assembled = Path(context["assembled_video"])
    work_dir = Path(context["work_dir"])
    input_video = str(context.get("input_video", assembled))

    emit_progress("assembly", "jump_cuts", 0.0, "Analyzing video dimensions...")

    # Get video dimensions
    info = probe_video_info(assembled)
    video_stream = next(
        (s for s in info.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if video_stream is None:
        logger.warning("No video stream found — skipping jump cuts.")
        return {}

    width: int = int(video_stream["width"])
    height: int = int(video_stream["height"])

    keep_segments: list[tuple[float, float]] = context.get("keep_segments", [])

    emit_progress("assembly", "jump_cuts", 0.1, "Computing zoom filter chain...")

    # Build per-segment crop parameters for odd segments
    # We apply zoom to the entire assembled video using a vf select+filter approach.
    # Since the assembled video has already been cut and concatenated, we need to
    # apply zoom based on the duration of each segment in the assembled output.
    segment_zooms = _compute_segment_zooms(
        input_video=input_video,
        keep_segments=keep_segments,
        zoom_factor=zoom_factor,
        width=width,
        height=height,
        face_smooth=face_smooth,
    )

    if not any(z["zoom"] for z in segment_zooms):
        # No odd segments — nothing to zoom
        emit_progress("assembly", "jump_cuts", 1.0, "No segments require zoom — skipping.")
        return {}

    output_path = work_dir / f"{assembled.stem}_jump_cuts{assembled.suffix}"
    filter_str = _build_zoom_filter(segment_zooms, width, height)

    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i", str(assembled),
        "-filter_complex", filter_str,
        "-map", "[outv]",
        "-map", "0:a",
        "-vcodec", "libx264",
        "-crf", "18",
        "-preset", "fast",
        "-acodec", "copy",
        str(output_path),
    ]

    emit_progress("assembly", "jump_cuts", 0.5, "Applying zoom punch-in effect...")
    run_ffmpeg(cmd)

    emit_progress("assembly", "jump_cuts", 1.0, "Jump cuts applied.")
    return {"assembled_video": str(output_path)}


def _compute_segment_zooms(
    input_video: str,
    keep_segments: list[tuple[float, float]],
    zoom_factor: float,
    width: int,
    height: int,
    face_smooth: bool,
) -> list[dict]:
    """Compute crop parameters for each segment.

    Returns a list of dicts with keys:
        - duration: segment duration in seconds
        - zoom: bool — whether this segment gets zoom
        - crop_x: pixel offset from left edge
        - crop_y: pixel offset from top edge
        - crop_w: cropped width
        - crop_h: cropped height
    """
    crop_w = int(width / zoom_factor)
    crop_h = int(height / zoom_factor)
    # Default center crop offsets
    center_x = (width - crop_w) // 2
    center_y = (height - crop_h) // 2

    result = []
    for i, (start, end) in enumerate(keep_segments):
        apply_zoom = (i % 2 == 1)  # odd segments get zoom
        crop_x = center_x
        crop_y = center_y

        if apply_zoom and face_smooth and keep_segments:
            # Sample face center from the original video for this segment
            try:
                positions = sample_face_positions(
                    input_video,
                    sample_interval_sec=max(1.0, (end - start) / 5),
                    duration_sec=end - start,
                )
                # Only sample within this segment's time range
                face = average_face_position(positions)
                if face is not None:
                    # Convert normalized face center to crop offset
                    # face_center_px is where we want the center of our crop window
                    face_px_x = int(face.cx * width)
                    face_px_y = int(face.cy * height)
                    # Offset the crop so face center aligns with crop center
                    raw_x = face_px_x - crop_w // 2
                    raw_y = face_px_y - crop_h // 2
                    # Clamp so crop stays within frame bounds
                    crop_x = max(0, min(width - crop_w, raw_x))
                    crop_y = max(0, min(height - crop_h, raw_y))
            except Exception as exc:
                logger.debug("Face detection failed for segment %d: %s — using center crop.", i, exc)

        result.append({
            "duration": end - start,
            "zoom": apply_zoom,
            "crop_x": crop_x,
            "crop_y": crop_y,
            "crop_w": crop_w,
            "crop_h": crop_h,
        })

    return result


def _build_zoom_filter(segment_zooms: list[dict], width: int, height: int) -> str:
    """Build an FFmpeg filter_complex string using split+trim+crop+scale+concat.

    Uses a split filter to fan out the single input stream to N branches,
    applies trim to each branch, optional crop+scale to odd segments, then
    concatenates all video streams. Audio is passed through unchanged.

    The filter outputs a labeled [outv] stream mapped by the caller.
    """
    n = len(segment_zooms)
    parts: list[str] = []
    labels: list[str] = []

    # Split the single video stream into N copies
    split_outputs = "".join(f"[split{i}]" for i in range(n))
    parts.append(f"[0:v]split={n}{split_outputs}")

    elapsed = 0.0
    for i, seg in enumerate(segment_zooms):
        dur = seg["duration"]
        seg_start = elapsed
        seg_end = elapsed + dur
        elapsed = seg_end

        v_label = f"[v{i}]"
        parts.append(
            f"[split{i}]trim=start={seg_start:.6f}:end={seg_end:.6f},"
            f"setpts=PTS-STARTPTS{v_label}"
        )

        if seg["zoom"]:
            cx, cy = seg["crop_x"], seg["crop_y"]
            cw, ch = seg["crop_w"], seg["crop_h"]
            zoomed_label = f"[vz{i}]"
            parts.append(
                f"{v_label}crop={cw}:{ch}:{cx}:{cy},"
                f"scale={width}:{height}{zoomed_label}"
            )
            labels.append(zoomed_label)
        else:
            labels.append(v_label)

    concat_part = "".join(labels) + f"concat=n={n}:v=1:a=0[outv]"
    parts.append(concat_part)

    return ";".join(parts)
