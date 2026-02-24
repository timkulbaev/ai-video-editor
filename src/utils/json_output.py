"""Structured JSON output to stdout and progress events to stderr.

Rule: JSON goes to stdout. Progress/logs go to stderr.
This allows AI agents to capture stdout as a clean JSON blob.
"""

from __future__ import annotations

import json
import sys
import time
from typing import Any


def emit_progress(
    phase: str,
    step: str,
    progress: float,
    message: str,
) -> None:
    """Write a progress event as a JSON line to stderr.

    Args:
        phase: Pipeline phase name (e.g., "analysis", "assembly").
        step: Step within the phase (e.g., "vad", "whisper").
        progress: Fractional progress within this step (0.0–1.0).
        message: Human-readable description of current activity.
    """
    event = {
        "phase": phase,
        "step": step,
        "progress": round(progress, 3),
        "message": message,
    }
    print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)


def emit_result(result: dict[str, Any]) -> None:
    """Write the final result as a JSON object to stdout."""
    print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stdout, flush=True)


def emit_error(message: str, code: str = "PIPELINE_ERROR") -> None:
    """Write an error result as a JSON object to stdout and exit non-zero."""
    result = {
        "status": "error",
        "error": {
            "code": code,
            "message": message,
        },
    }
    print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stdout, flush=True)
    sys.exit(1)


class Timer:
    """Simple wall-clock timer for measuring processing time."""

    def __init__(self) -> None:
        self._start = time.monotonic()

    def elapsed(self) -> float:
        """Return elapsed seconds since timer creation."""
        return round(time.monotonic() - self._start, 1)
