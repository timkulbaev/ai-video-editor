"""Silero VAD speech segment detection."""

from __future__ import annotations

import struct
import wave
from pathlib import Path
from typing import Any

from ..utils.json_output import emit_progress


def _load_wav_as_tensor(wav_path: str) -> "torch.FloatTensor":
    """Load a 16kHz mono WAV file as a normalized float32 tensor.

    Uses only Python stdlib (wave module) — no torchaudio or soundfile needed.
    The WAV must be 16-bit PCM mono at 16000 Hz (the format extract_audio produces).
    """
    import torch

    with wave.open(wav_path, "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sampwidth != 2:
        raise ValueError(f"Expected 16-bit PCM, got {sampwidth * 8}-bit in {wav_path}")
    if framerate != 16000:
        raise ValueError(f"Expected 16000 Hz sample rate, got {framerate} in {wav_path}")

    # Decode 16-bit signed little-endian samples
    n_samples = len(raw) // 2
    samples = struct.unpack(f"<{n_samples}h", raw)

    # If stereo, take only the first channel
    if n_channels > 1:
        samples = samples[::n_channels]

    # Normalize to [-1, 1] float32
    tensor = torch.tensor(samples, dtype=torch.float32) / 32768.0
    return tensor


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Run Silero VAD on the extracted WAV and return speech segments.

    Args:
        context: Pipeline state. Reads:
            - "audio_wav": Path to a 16kHz mono WAV file
        config: Full pipeline config. Reads config["silence"].

    Returns:
        {"speech_segments": list[dict]} — [{"start": float, "end": float}, ...]

    Notes:
        Silero VAD model is loaded via torch.hub on first call
        and cached in ~/.cache/torch/hub/. Download is ~1.8 MB.
        Audio loading uses Python stdlib wave module — no torchaudio backend needed.
    """
    emit_progress("analysis", "vad", 0.0, "Loading Silero VAD model...")

    try:
        import torch
    except ImportError as e:
        raise ImportError(
            "PyTorch is required for speech detection. "
            "Install with: uv pip install torch"
        ) from e

    silence_cfg = config.get("silence", {})
    min_silence_ms = silence_cfg.get("min_silence_ms", 500)
    padding_ms = silence_cfg.get("padding_ms", 100)

    wav_path = context["audio_wav"]

    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        onnx=False,
        verbose=False,
    )

    get_speech_timestamps = utils[0]

    emit_progress("analysis", "vad", 0.3, "Running speech detection...")

    # Load WAV using stdlib — avoids torchaudio backend compatibility issues
    wav = _load_wav_as_tensor(str(wav_path))

    speech_timestamps = get_speech_timestamps(
        wav,
        model,
        sampling_rate=16000,
        min_silence_duration_ms=min_silence_ms,
        speech_pad_ms=padding_ms,
        return_seconds=True,
    )

    segments = [
        {"start": float(ts["start"]), "end": float(ts["end"])}
        for ts in speech_timestamps
    ]

    emit_progress(
        "analysis",
        "vad",
        1.0,
        f"Speech detection complete: {len(segments)} speech segments found",
    )
    return {"speech_segments": segments}
