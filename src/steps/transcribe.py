"""faster-whisper transcription with word-level timestamps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..utils.json_output import emit_progress


@dataclass
class Word:
    """A single transcribed word with timing."""
    word: str
    start: float
    end: float
    probability: float


@dataclass
class TranscriptSegment:
    """A transcribed sentence/phrase with its constituent words."""
    text: str
    start: float
    end: float
    words: list[Word]


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Transcribe audio using faster-whisper with word-level timestamps.

    Args:
        context: Pipeline state. Reads:
            - "audio_wav": Path to WAV audio file
        config: Full pipeline config. Reads config["whisper"].

    Returns:
        {"transcript": list[dict]} — list of segment dicts with word timestamps.

    Notes:
        On first run the model (~3 GB for large-v3) is downloaded to
        ~/.cache/huggingface/. Subsequent runs use the cached model.
    """
    whisper_cfg = config.get("whisper", {})
    model_name = whisper_cfg.get("model", "large-v3")
    language = whisper_cfg.get("language", "auto")
    device = whisper_cfg.get("device", "cpu")

    emit_progress("analysis", "whisper", 0.0, f"Loading Whisper {model_name} model...")

    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise ImportError(
            "faster-whisper is required for transcription. "
            "Install with: uv pip install faster-whisper"
        ) from e

    wav_path = context["audio_wav"]
    model = WhisperModel(model_name, device=device, compute_type="int8")

    emit_progress("analysis", "whisper", 0.2, "Transcribing audio (this may take several minutes)...")

    lang = None if language == "auto" else language
    raw_segments, info = model.transcribe(
        str(wav_path),
        language=lang,
        word_timestamps=True,
        vad_filter=False,  # Our own Silero VAD handles silence removal
    )

    emit_progress(
        "analysis",
        "whisper",
        0.5,
        f"Detected language: {info.language} (confidence: {info.language_probability:.2f})",
    )

    segment_list = list(raw_segments)  # consume generator
    total = len(segment_list)
    segments = []

    for i, seg in enumerate(segment_list):
        words = []
        if seg.words:
            for w in seg.words:
                words.append({
                    "word": w.word,
                    "start": w.start,
                    "end": w.end,
                    "probability": w.probability,
                })
        segments.append({
            "text": seg.text.strip(),
            "start": seg.start,
            "end": seg.end,
            "words": words,
        })

        if total > 0 and i % max(1, total // 10) == 0:
            progress = 0.5 + 0.5 * (i / total)
            emit_progress("analysis", "whisper", progress, f"Transcribed {i}/{total} segments...")

    emit_progress(
        "analysis",
        "whisper",
        1.0,
        f"Transcription complete: {len(segments)} segments, "
        f"{sum(len(s['words']) for s in segments)} words",
    )
    return {
        "transcript": segments,
        "detected_language": info.language,
    }
