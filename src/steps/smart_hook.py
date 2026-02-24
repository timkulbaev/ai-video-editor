"""Smart hook step — uses OpenRouter LLM to identify the most engaging 5-10s intro hook."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from ..utils.json_output import emit_progress
from ..utils.openrouter import chat_completion, OpenRouterError

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a video editor assistant. Your task is to analyze a video transcript and identify
the single most engaging, surprising, or curiosity-inducing segment that would work as a
hook at the start of a YouTube video. The hook should make viewers want to keep watching.

Respond with a JSON object only. No explanation, no markdown. Format:
{
  "start": <float seconds>,
  "end": <float seconds>,
  "reason": "<one sentence explaining why this is the best hook>"
}

Rules:
- The segment must be 5-10 seconds long (end - start must be between 5.0 and 10.0).
- Choose a moment with a surprising fact, bold claim, conflict, or strong emotion.
- Avoid intros, greetings, and filler content.
- The timestamps must be real timestamps from the transcript.
"""


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Find the most engaging hook segment using an LLM analysis of the transcript.

    If OPENROUTER_API_KEY is not set or the call fails, logs a warning and
    returns empty dict so the pipeline continues without a hook.

    Args:
        context: Pipeline state. Reads:
            - "transcript": Whisper transcript dict with word timestamps
        config: Full pipeline config. Reads config["hook"].

    Returns:
        {"hook_segment": {"start": float, "end": float}} if successful,
        or empty dict if API key is missing or call fails.
    """
    hook_cfg = config.get("hook", {})

    if not hook_cfg.get("enabled", True):
        emit_progress("ai", "smart_hook", 1.0, "Smart hook disabled — skipping.")
        return {}

    import os
    if not os.environ.get("OPENROUTER_API_KEY"):
        logger.warning(
            "OPENROUTER_API_KEY not set — skipping smart hook generation. "
            "Set this env var to enable hook detection."
        )
        emit_progress("ai", "smart_hook", 1.0, "Smart hook skipped (no API key).")
        return {}

    transcript = context.get("transcript")
    if not transcript:
        logger.warning("No transcript in context — skipping smart hook.")
        emit_progress("ai", "smart_hook", 1.0, "Smart hook skipped (no transcript).")
        return {}

    emit_progress("ai", "smart_hook", 0.0, "Analyzing transcript for best hook segment...")

    model = hook_cfg.get("model", "anthropic/claude-sonnet-4")
    transcript_text = _format_transcript_for_llm(transcript)

    prompt = (
        f"Here is the video transcript with timestamps:\n\n{transcript_text}\n\n"
        f"Identify the best 5-10 second hook segment."
    )

    try:
        emit_progress("ai", "smart_hook", 0.3, f"Sending transcript to {model}...")
        response_text = chat_completion(
            prompt=prompt,
            model=model,
            system=_SYSTEM_PROMPT,
            temperature=0.3,
            max_tokens=256,
        )
    except OpenRouterError as exc:
        logger.warning("OpenRouter API error during hook detection: %s — skipping.", exc)
        emit_progress("ai", "smart_hook", 1.0, "Smart hook skipped (API error).")
        return {}
    except Exception as exc:
        logger.warning("Unexpected error during hook detection: %s — skipping.", exc)
        emit_progress("ai", "smart_hook", 1.0, "Smart hook skipped (unexpected error).")
        return {}

    hook = _parse_hook_response(response_text)
    if hook is None:
        logger.warning("Could not parse hook segment from LLM response — skipping.")
        emit_progress("ai", "smart_hook", 1.0, "Smart hook skipped (invalid LLM response).")
        return {}

    emit_progress(
        "ai", "smart_hook", 1.0,
        f"Hook identified: {hook['start']:.1f}s–{hook['end']:.1f}s"
    )
    return {"hook_segment": hook}


def _format_transcript_for_llm(transcript: Any) -> str:
    """Format a Whisper transcript into a timestamped text representation.

    Handles both faster-whisper segment format (list of dicts with start/end/text)
    and plain string transcripts.
    """
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
            end = seg.get("end", 0.0)
            text = seg.get("text", "").strip()
            if text:
                lines.append(f"[{start:.1f}s–{end:.1f}s] {text}")

    return "\n".join(lines) if lines else str(transcript)


def _parse_hook_response(response_text: str) -> dict[str, float] | None:
    """Parse the LLM JSON response and validate the hook segment.

    Returns {"start": float, "end": float} or None on failure.
    """
    # Strip markdown code fences if present
    text = response_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from anywhere in the response
        match = re.search(r'\{[^{}]*"start"[^{}]*"end"[^{}]*\}', text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            return None

    start = data.get("start")
    end = data.get("end")

    if start is None or end is None:
        return None

    try:
        start = float(start)
        end = float(end)
    except (TypeError, ValueError):
        return None

    # Validate duration is within the 5-10 second range
    duration = end - start
    if duration < 3.0 or duration > 15.0:
        logger.warning(
            "Hook duration %.1fs is outside expected range (3-15s) — using anyway.", duration
        )

    if start < 0 or end <= start:
        return None

    return {"start": start, "end": end}
