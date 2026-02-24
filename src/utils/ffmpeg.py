"""FFmpeg subprocess wrapper — run commands, parse output, handle errors."""

from __future__ import annotations

import subprocess
import shutil
from pathlib import Path
from typing import Sequence


class FFmpegError(RuntimeError):
    """Raised when an FFmpeg command exits with a non-zero status."""

    def __init__(self, cmd: list[str], returncode: int, stderr: str) -> None:
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(
            f"FFmpeg exited {returncode}.\nCommand: {' '.join(cmd)}\nStderr: {stderr[-2000:]}"
        )


def ffmpeg_bin() -> str:
    """Return the path to the ffmpeg binary, raising if not found."""
    path = shutil.which("ffmpeg")
    if path is None:
        raise EnvironmentError(
            "ffmpeg not found in PATH. Install via: brew install ffmpeg"
        )
    return path


def ffprobe_bin() -> str:
    """Return the path to the ffprobe binary, raising if not found."""
    path = shutil.which("ffprobe")
    if path is None:
        raise EnvironmentError(
            "ffprobe not found in PATH. Install via: brew install ffmpeg"
        )
    return path


def run(args: Sequence[str], capture_stderr: bool = True) -> subprocess.CompletedProcess:
    """Run an FFmpeg command.

    Args:
        args: Full command line including 'ffmpeg' as the first element.
        capture_stderr: If True, capture stderr (suppresses terminal output).
                        Set False when you want live FFmpeg progress in the terminal.

    Returns:
        CompletedProcess with stdout and stderr (bytes).

    Raises:
        FFmpegError: If the process exits with a non-zero code.
    """
    cmd = list(args)
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE if capture_stderr else None,
        text=False,  # bytes mode — caller decodes as needed
    )
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        raise FFmpegError(cmd, result.returncode, stderr_text)
    return result


def probe_duration(video_path: str | Path) -> float:
    """Return the duration of a media file in seconds using ffprobe."""
    cmd = [
        ffprobe_bin(),
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        str(video_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise FFmpegError(cmd, result.returncode, result.stderr)

    import json
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def probe_video_info(video_path: str | Path) -> dict:
    """Return format + stream info for a media file using ffprobe."""
    cmd = [
        ffprobe_bin(),
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise FFmpegError(cmd, result.returncode, result.stderr)

    import json
    return json.loads(result.stdout)


def build_filter_complex(segments: list[dict], video_width: int, video_height: int) -> str:
    """Build an FFmpeg filter_complex string for segment assembly with optional zoom.

    Each segment dict must have: start (float), end (float), zoom (bool).
    Returns the filter_complex string (without -filter_complex flag).
    """
    parts: list[str] = []
    labels: list[str] = []

    for i, seg in enumerate(segments):
        v_in = f"[v{i}]"
        a_in = f"[a{i}]"

        # Trim the segment
        trim = f"[0:v]trim=start={seg['start']}:end={seg['end']},setpts=PTS-STARTPTS{v_in}"
        atrim = f"[0:a]atrim=start={seg['start']}:end={seg['end']},asetpts=PTS-STARTPTS{a_in}"
        parts.append(trim)
        parts.append(atrim)

        # Optional zoom punch-in (crop to zoom_factor, then scale back)
        if seg.get("zoom"):
            zoom = seg.get("zoom_factor", 1.05)
            crop_w = int(video_width / zoom)
            crop_h = int(video_height / zoom)
            crop_x = (video_width - crop_w) // 2
            crop_y = (video_height - crop_h) // 2
            zoomed = f"[v{i}]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={video_width}:{video_height}[vz{i}]"
            parts.append(zoomed)
            labels.append(f"[vz{i}][a{i}]")
        else:
            labels.append(f"[v{i}][a{i}]")

    n = len(segments)
    concat = "".join(labels) + f"concat=n={n}:v=1:a=1[outv][outa]"
    parts.append(concat)

    return ";".join(parts)
