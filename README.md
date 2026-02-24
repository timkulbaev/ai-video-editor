# AI Video Editor

AI-powered CLI tool for automatic talking-head video editing.

## Features

- **Silence removal** — Silero VAD strips dead air; short natural pauses are preserved
- **Filler word removal** — English and Russian filler words ("um", "uh", "ну", "типа", "эээ", ...)
- **Restart phrase detection** — "cut cut" / "кат кат" removes the entire failed take automatically
- **Repeated sentence detection** — auto-detects and cuts duplicate sentence starts
- **Smart hook generation** — OpenRouter LLM picks the best 8-second opener (optional)
- **YouTube chapter markers** — LLM generates timestamped chapters from the transcript (optional)
- **Hardware encoding** — `h264_videotoolbox` on Apple Silicon for fast final encode
- **Configurable YAML pipeline** — every threshold, model, and feature toggle is overridable

## Requirements

- Python 3.11+
- FFmpeg 7+ (`brew install ffmpeg`)
- macOS with Apple Silicon (for VideoToolbox hardware encoding; falls back to libx264 elsewhere)
- ~4 GB RAM for Whisper `large-v3` (use `--whisper-model small` for lighter machines)

## Installation

```bash
cd Tools/ai-video-editor
uv venv
source .venv/bin/activate
uv pip install -e .
```

## Quick Start

```bash
ai-video-editor process video.mp4 --no-hook --no-chapters
```

Example output (stdout):

```json
{
  "status": "complete",
  "input": "video.mp4",
  "output_video": "video_edited.mp4",
  "duration_original_sec": 154.6,
  "duration_edited_sec": 145.9,
  "segments_removed": 1,
  "silence_removed_sec": 2.1,
  "restarts_removed": 1,
  "fillers_removed": 4
}
```

Progress events are emitted to stderr as JSON lines during processing.

## CLI Commands

### `process` — Edit a video

```
ai-video-editor process VIDEO [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--config, -c PATH` | Custom YAML config file (merged over defaults) |
| `--whisper-model, -m MODEL` | Whisper model size: tiny / base / small / medium / large / large-v3 |
| `--lut PATH` | Path to a `.cube` LUT file for color grading |
| `--output, -o PATH` | Output file path (default: `{input}_edited.mp4`) |
| `--no-hook` | Skip smart hook generation (no OpenRouter call) |
| `--no-chapters` | Skip YouTube chapter generation (no OpenRouter call) |

### `info` — Inspect a video file

```
ai-video-editor info VIDEO
```

Prints codec, resolution, FPS, duration, and bitrate as JSON.

### `models` — List Whisper model sizes

```
ai-video-editor models
```

## Configuration

The default config lives in `config.default.yml`. Override any section with `--config my.yml` — your file is deep-merged over the defaults, so you only need to specify what changes.

| Section | Key settings |
|---------|-------------|
| `whisper` | `model`, `language`, `device` |
| `silence` | `min_gap_sec` (merge threshold), `padding_sec` (breathing room at cuts) |
| `restarts` | `enabled`, `trigger_phrases`, `detect_repeated_starts` |
| `fillers` | `enabled`, `min_filler_duration_sec`, `words.en`, `words.ru` |
| `audio` | `enabled` (off by default), noise reduction and loudness settings |
| `video` | `lut_path`, `zoom_punch.enabled`, `position_smoothing.enabled` |
| `hook` | `enabled`, `duration_sec`, `model` |
| `chapters` | `enabled`, `model` |
| `encoding` | `codec`, `quality`, `audio_codec`, `audio_bitrate` |

Example override — use a smaller Whisper model and enable audio enhancement:

```yaml
# my-config.yml
whisper:
  model: small
audio:
  enabled: true
```

```bash
ai-video-editor process video.mp4 --config my-config.yml
```

## How It Works

The pipeline runs four sequential phases:

1. **Analysis** — Extract audio → Silero VAD (speech segments) → Whisper transcription → edit decisions (merge short gaps, remove restarts and fillers, apply padding)
2. **Assembly** — Frame-accurate FFmpeg segment extraction → concat → optional zoom punch-in → optional audio enhancement → optional LUT color grade
3. **AI Enhancement** — Smart hook selection and YouTube chapters via OpenRouter (skipped if `--no-hook --no-chapters` or no API key)
4. **Encode** — Final h264_videotoolbox (or libx264) encode with AAC audio, optimized for web playback

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | Required for hook generation and chapter markers. Set in a `.env` file next to `pyproject.toml` or export in your shell. Without it, AI enhancement steps are skipped gracefully. |

## License

MIT — see [LICENSE](LICENSE).
