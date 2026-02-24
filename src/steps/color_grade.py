"""Color grading step — applies a .cube LUT to the video via FFmpeg."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..utils.ffmpeg import ffmpeg_bin
from ..utils.ffmpeg import run as run_ffmpeg
from ..utils.json_output import emit_progress

logger = logging.getLogger(__name__)


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Apply LUT color grading to the assembled video.

    Reads config["video"]["lut_path"]. If null or not set, this step is a no-op.

    Args:
        context: Pipeline state. Reads:
            - "assembled_video": Path to assembled video file
            - "work_dir": Path to temporary working directory
        config: Full pipeline config. Reads config["video"]["lut_path"].

    Returns:
        {"assembled_video": Path} — updated path pointing to the color-graded video,
        or empty dict if LUT was not applied.
    """
    lut_path = config.get("video", {}).get("lut_path")

    if not lut_path:
        emit_progress("assembly", "color_grade", 1.0, "Color grading skipped (no LUT configured).")
        return {}

    lut_path = Path(lut_path)
    if not lut_path.exists():
        logger.warning("LUT file not found at %s — skipping color grading.", lut_path)
        emit_progress("assembly", "color_grade", 1.0, f"Color grading skipped (LUT not found: {lut_path}).")
        return {}

    emit_progress("assembly", "color_grade", 0.0, f"Applying LUT: {lut_path.name}...")

    assembled = Path(context["assembled_video"])
    work_dir = Path(context["work_dir"])
    output_path = work_dir / f"{assembled.stem}_color_graded{assembled.suffix}"

    # lut3d filter applies a .cube 3D LUT to the video stream
    cmd = [
        ffmpeg_bin(),
        "-y",
        "-i", str(assembled),
        "-vf", f"lut3d={str(lut_path)}",
        "-vcodec", "libx264",   # re-encode video with LUT applied
        "-crf", "18",           # high quality intermediate (will be re-encoded by encode step)
        "-preset", "fast",
        "-acodec", "copy",      # copy audio unchanged
        str(output_path),
    ]

    emit_progress("assembly", "color_grade", 0.3, "Running FFmpeg LUT application...")
    run_ffmpeg(cmd)

    emit_progress("assembly", "color_grade", 1.0, "Color grading applied.")
    return {"assembled_video": str(output_path)}
