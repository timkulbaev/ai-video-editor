# AI Video Editor

A local, open-source CLI tool that automatically edits talking-head videos using AI. Point it at a raw recording and it removes silences, filler words ("um", "uh", "ну", "типа"), and failed takes (say "cut cut" to mark a restart). It uses Silero VAD for speech detection, Whisper large-v3 for transcription with word-level timestamps, and FFmpeg for frame-accurate assembly. Optionally generates a smart hook opener and YouTube chapter markers via LLM. Runs entirely on your machine — no cloud APIs required for the core pipeline. Designed to be invoked by AI agents (structured JSON output) or used as an MCP server in Claude Desktop.

## Features

- **Silence removal** — Silero VAD strips dead air; short natural pauses are preserved
- **Filler word removal** — English and Russian filler words ("um", "uh", "ну", "типа", "эээ", ...)
- **Restart detection** — "cut cut" / "кат кат" removes the entire failed take; short isolated bursts (coughs, false starts) are auto-removed via VAD duration filtering
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
# Core editing only (no API calls)
ai-video-editor process video.mp4 --no-hook --no-chapters

# Full pipeline with smart hook opener + YouTube chapters (requires OPENROUTER_API_KEY)
ai-video-editor process video.mp4
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
| `restarts` | `enabled`, `trigger_phrases`, `detect_repeated_starts`, `max_burst_duration_sec` |
| `fillers` | `enabled`, `min_filler_duration_sec`, `words.en`, `words.ru` |
| `audio` | `enabled` (off by default), noise reduction and loudness settings |
| `video` | `lut_path` |
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

1. **Analysis** — Extract audio → Silero VAD (speech segments) → Whisper transcription → edit decisions (remove short bursts, merge short gaps, remove restarts and fillers, apply padding)
2. **Assembly** — Frame-accurate FFmpeg segment extraction → concat → optional audio enhancement → optional LUT color grade
3. **AI Enhancement** — Smart hook selection and YouTube chapters via OpenRouter (skipped if `--no-hook --no-chapters` or no API key)
4. **Encode** — Final h264_videotoolbox (or libx264) encode with AAC audio, optimized for web playback

## Claude Desktop (MCP Server)

The tool includes a built-in MCP server so Claude Desktop can use it as a native capability.

**Setup:**

1. Add to your `claude_desktop_config.json` (see `claude_desktop_config.example.json` for the template):

```json
"ai-video-editor": {
  "command": "/path/to/ai-video-editor/.venv/bin/python",
  "args": ["-m", "src.mcp_server"],
  "cwd": "/path/to/ai-video-editor"
}
```

2. Restart Claude Desktop.
3. Optionally install `SKILL.md` as a capability for model selection guidance and workflow tips.

Claude gets three tools: `process_video`, `video_info`, and `list_models`.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | Required for smart hook and chapter generation. Set in a `.env` file next to `pyproject.toml` or export in your shell. Without it, AI enhancement steps are skipped gracefully. Get a key at [openrouter.ai/keys](https://openrouter.ai/keys). |
| `OPENROUTER_REFERER` | Optional. Shown in your OpenRouter usage dashboard for attribution tracking. |

## License

MIT — see [LICENSE](LICENSE).
