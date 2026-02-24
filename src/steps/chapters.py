"""Chapters step — uses OpenRouter LLM to generate YouTube chapter markers."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from ..utils.json_output import emit_progress
from ..utils.openrouter import chat_completion, OpenRouterError

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a YouTube video editor assistant. Your task is to analyze a video transcript
and generate chapter markers for a YouTube video description.

Respond with a JSON object only. No explanation, no markdown. Format:
{
  "chapters": [
    {"time": "0:00", "title": "Introduction"},
    {"time": "1:23", "title": "Main Topic"},
    ...
  ]
}

Rules:
- First chapter must start at "0:00".
- Use MM:SS format for videos under 1 hour, H:MM:SS for longer videos.
- Titles should be concise (2-5 words), descriptive, and engaging.
- Generate 3-10 chapters depending on content length and distinct sections.
- Timestamps must be in ascending order and match real content transitions in the transcript.
- Do not include chapter numbers in titles (YouTube adds them automatically).
"""


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Generate YouTube chapter markers from the video transcript using an LLM.

    Saves chapters to a .chapters.txt file alongside the output video.
    If OPENROUTER_API_KEY is not set or the call fails, skips gracefully.

    Args:
        context: Pipeline state. Reads:
            - "transcript": Whisper transcript dict with word timestamps
            - "output_video": Path to final output video (used to derive chapters file path)
            - "input_video": Fallback for deriving output path
        config: Full pipeline config. Reads config["chapters"].

    Returns:
        {"chapters": list, "chapters_file": str} if successful, or empty dict.
    """
    chapters_cfg = config.get("chapters", {})

    if not chapters_cfg.get("enabled", True):
        emit_progress("ai", "chapters", 1.0, "Chapter generation disabled — skipping.")
        return {}

    if not os.environ.get("OPENROUTER_API_KEY"):
        logger.warning(
            "OPENROUTER_API_KEY not set — skipping chapter generation. "
            "Set this env var to enable chapter markers."
        )
        emit_progress("ai", "chapters", 1.0, "Chapter generation skipped (no API key).")
        return {}

    transcript = context.get("transcript")
    if not transcript:
        logger.warning("No transcript in context — skipping chapter generation.")
        emit_progress("ai", "chapters", 1.0, "Chapter generation skipped (no transcript).")
        return {}

    emit_progress("ai", "chapters", 0.0, "Generating YouTube chapter markers...")

    model = chapters_cfg.get("model", "anthropic/claude-sonnet-4")
    transcript_text = _format_transcript_for_llm(transcript)

    prompt = (
        f"Here is the video transcript with timestamps:\n\n{transcript_text}\n\n"
        f"Generate YouTube chapter markers for this video."
    )

    try:
        emit_progress("ai", "chapters", 0.3, f"Sending transcript to {model}...")
        response_text = chat_completion(
            prompt=prompt,
            model=model,
            system=_SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=512,
        )
    except OpenRouterError as exc:
        logger.warning("OpenRouter API error during chapter generation: %s — skipping.", exc)
        emit_progress("ai", "chapters", 1.0, "Chapter generation skipped (API error).")
        return {}
    except Exception as exc:
        logger.warning("Unexpected error during chapter generation: %s — skipping.", exc)
        emit_progress("ai", "chapters", 1.0, "Chapter generation skipped (unexpected error).")
        return {}

    chapters = _parse_chapters_response(response_text)
    if not chapters:
        logger.warning("Could not parse chapters from LLM response — skipping.")
        emit_progress("ai", "chapters", 1.0, "Chapter generation skipped (invalid LLM response).")
        return {}

    # Determine output path for the chapters file
    chapters_file = _get_chapters_file_path(context)
    _write_chapters_file(chapters_file, chapters)

    emit_progress(
        "ai", "chapters", 1.0,
        f"Generated {len(chapters)} chapters → {Path(chapters_file).name}"
    )
    return {"chapters": chapters, "chapters_file": str(chapters_file)}


def _format_transcript_for_llm(transcript: Any) -> str:
    """Format a Whisper transcript into a timestamped text representation."""
    if isinstance(transcript, str):
        return transcript

    if isinstance(transcript, dict):
        segments = transcript.get("segments", [])
    elif isinstance(transcript, list):
        segments = transcript
    else:
        return str(transcript)

    lines = []
    for seg in segments:
        if isinstance(seg, dict):
            start = seg.get("start", 0.0)
            text = seg.get("text", "").strip()
            if text:
                lines.append(f"[{_format_timestamp(start)}] {text}")

    return "\n".join(lines) if lines else str(transcript)


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to MM:SS or H:MM:SS string."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _parse_chapters_response(response_text: str) -> list[dict] | None:
    """Parse the LLM JSON response and validate the chapters list."""
    text = response_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON anywhere in the response
        match = re.search(r'\{[^{}]*"chapters"[^{}]*\[.*?\]\s*\}', text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return None

    chapters = data.get("chapters")
    if not isinstance(chapters, list) or not chapters:
        return None

    validated = []
    for ch in chapters:
        if not isinstance(ch, dict):
            continue
        time_val = ch.get("time")
        title = ch.get("title", "").strip()
        if time_val and title:
            validated.append({"time": str(time_val), "title": title})

    return validated if validated else None


def _get_chapters_file_path(context: dict[str, Any]) -> str:
    """Derive the chapters file path from output_video or input_video in context."""
    output_video = context.get("output_video") or context.get("input_video")
    if output_video:
        base = Path(output_video).with_suffix("")
        return str(base.parent / f"{base.name}.chapters.txt")
    return "output.chapters.txt"


def _write_chapters_file(path: str, chapters: list[dict]) -> None:
    """Write chapters to a text file in YouTube description format."""
    lines = [f"{ch['time']} {ch['title']}" for ch in chapters]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
