"""Typer CLI entry point for the AI Video Editor."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import print as rprint

app = typer.Typer(
    name="ai-video-editor",
    help="AI-powered CLI tool for automatic talking-head video editing.",
    add_completion=False,
)

console = Console(stderr=True)  # progress/info to stderr, JSON to stdout
err_console = Console(stderr=True)


# ---------------------------------------------------------------------------
# process command
# ---------------------------------------------------------------------------

@app.command()
def process(
    video: Path = typer.Argument(..., help="Path to the input video file."),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to a custom YAML config file (merged over defaults).",
    ),
    whisper_model: Optional[str] = typer.Option(
        None,
        "--whisper-model",
        "-m",
        help="Override Whisper model size (tiny/base/small/medium/large/large-v3).",
    ),
    lut: Optional[Path] = typer.Option(
        None,
        "--lut",
        help="Path to a .cube LUT file for color grading.",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output video path (default: {input_name}_edited.mp4 in same dir).",
    ),
    no_hook: bool = typer.Option(
        False,
        "--no-hook",
        is_flag=True,
        help="Skip smart hook generation (no OpenRouter call).",
    ),
    no_chapters: bool = typer.Option(
        False,
        "--no-chapters",
        is_flag=True,
        help="Skip YouTube chapter generation (no OpenRouter call).",
    ),
) -> None:
    """Process a video: remove silences, enhance audio, apply color grade, generate hook + chapters."""
    # Load .env file if present alongside the video or in the tool directory
    _load_dotenv()

    if not video.exists():
        err_console.print(f"[red]Error:[/red] Input video not found: {video}")
        _emit_error(f"Input video not found: {video}", "INPUT_NOT_FOUND")
        raise typer.Exit(code=1)

    from .pipeline import run_pipeline, PipelineError
    from .utils.json_output import emit_result, emit_error

    try:
        result = run_pipeline(
            input_video=video,
            config_path=config,
            whisper_model=whisper_model,
            lut_path=lut,
            output_path=output,
            no_hook=no_hook,
            no_chapters=no_chapters,
        )
        emit_result(result)
    except PipelineError as e:
        err_console.print(f"[red]Pipeline error:[/red] {e}")
        _emit_error(str(e), "PIPELINE_ERROR")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        err_console.print("[yellow]Interrupted.[/yellow]")
        _emit_error("Interrupted by user", "INTERRUPTED")
        raise typer.Exit(code=130)
    except Exception as e:
        err_console.print(f"[red]Unexpected error:[/red] {e}")
        _emit_error(str(e), "UNEXPECTED_ERROR")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# info command
# ---------------------------------------------------------------------------

@app.command()
def info(
    video: Path = typer.Argument(..., help="Path to the video file to inspect."),
) -> None:
    """Show metadata about a video file (duration, codec, resolution, audio)."""
    if not video.exists():
        err_console.print(f"[red]Error:[/red] File not found: {video}")
        _emit_error(f"File not found: {video}", "FILE_NOT_FOUND")
        raise typer.Exit(code=1)

    from .utils.ffmpeg import probe_video_info

    try:
        data = probe_video_info(video)
    except Exception as e:
        err_console.print(f"[red]Error probing video:[/red] {e}")
        raise typer.Exit(code=1)

    fmt = data.get("format", {})
    streams = data.get("streams", [])

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    # Build a clean info dict for JSON output
    info_dict: dict = {
        "file": str(video),
        "format": fmt.get("format_long_name", fmt.get("format_name")),
        "duration_sec": round(float(fmt.get("duration", 0)), 2),
        "size_mb": round(int(fmt.get("size", 0)) / (1024 * 1024), 2),
        "bit_rate_kbps": round(int(fmt.get("bit_rate", 0)) / 1000, 1),
    }

    if video_stream:
        info_dict["video"] = {
            "codec": video_stream.get("codec_name"),
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "fps": _parse_fps(video_stream.get("avg_frame_rate", "0/1")),
        }

    if audio_stream:
        info_dict["audio"] = {
            "codec": audio_stream.get("codec_name"),
            "sample_rate": audio_stream.get("sample_rate"),
            "channels": audio_stream.get("channels"),
        }

    # JSON to stdout (for AI agent consumption)
    print(json.dumps(info_dict, indent=2), flush=True)


# ---------------------------------------------------------------------------
# models command
# ---------------------------------------------------------------------------

@app.command()
def models() -> None:
    """List available Whisper model sizes with size and speed information."""
    model_info = [
        ("tiny",    "~39 MB",   "~32x realtime",  "Basic accuracy"),
        ("base",    "~74 MB",   "~16x realtime",  "Decent accuracy"),
        ("small",   "~244 MB",  "~6x realtime",   "Good accuracy"),
        ("medium",  "~769 MB",  "~2x realtime",   "Great accuracy"),
        ("large",   "~1.5 GB",  "~1x realtime",   "Excellent accuracy"),
        ("large-v2","~1.5 GB",  "~1x realtime",   "Improved large"),
        ("large-v3","~1.5 GB",  "~1x realtime",   "Best accuracy (default)"),
    ]

    table = Table(title="Available Whisper Models", show_header=True)
    table.add_column("Model", style="cyan")
    table.add_column("Size", style="green")
    table.add_column("Speed (CPU)", style="yellow")
    table.add_column("Notes", style="white")

    for row in model_info:
        table.add_row(*row)

    # Print the table to stderr (it's visual, not machine-readable)
    Console(stderr=True).print(table)

    # JSON list to stdout
    models_dict = [
        {"name": m[0], "size": m[1], "speed_cpu": m[2], "notes": m[3]}
        for m in model_info
    ]
    print(json.dumps(models_dict, indent=2), flush=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_dotenv() -> None:
    """Load .env file from the tool directory if present.

    Reads simple KEY=VALUE lines. Does not require python-dotenv.
    """
    dotenv_paths = [
        Path(__file__).parent.parent / ".env",
    ]
    for path in dotenv_paths:
        if path.exists():
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
            break


def _emit_error(message: str, code: str) -> None:
    """Write an error JSON object to stdout for AI agent consumption."""
    error_result = {
        "status": "error",
        "error": {"code": code, "message": message},
    }
    print(json.dumps(error_result, indent=2), flush=True)


def _parse_fps(fps_str: str) -> float | None:
    """Parse an FFmpeg rational FPS string like '30000/1001' into a float."""
    try:
        parts = fps_str.split("/")
        if len(parts) == 2:
            return round(int(parts[0]) / int(parts[1]), 3)
        return float(fps_str)
    except (ValueError, ZeroDivisionError):
        return None


if __name__ == "__main__":
    app()
