# Contributing

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Requires FFmpeg (`brew install ffmpeg` on macOS) and PyTorch (`pip install torch`).

## Project structure

```
src/
  cli.py               # Typer CLI entry point — process, info, models commands
  pipeline.py          # Step orchestrator — reads context, calls steps in order
  config.py            # YAML config loader with deep merge and validation
  mcp_server.py        # MCP server (FastMCP) — exposes CLI tools to Claude Desktop
  steps/
    extract_audio.py   # FFmpeg audio extraction — produces 16kHz mono WAV
    detect_speech.py   # Silero VAD — produces speech_segments
    transcribe.py      # faster-whisper — produces transcript with word timestamps
    edit_decisions.py  # Merge, filter, pad segments — produces keep_segments
    assemble.py        # FFmpeg extract + concat — produces assembled_video
    enhance_audio.py   # Optional audio polish chain
    color_grade.py     # Optional .cube LUT color grading
    smart_hook.py      # Optional AI hook via OpenRouter
    chapters.py        # Optional YouTube chapters via OpenRouter
    encode.py          # Final VideoToolbox/libx264 encode
  utils/
    ffmpeg.py          # FFmpeg wrappers (run, probe, bin detection)
    openrouter.py      # OpenRouter API client (chat completion)
    json_output.py     # emit_progress / emit_error helpers
config.default.yml     # Baseline config (all features documented)
```

## Adding a pipeline step

1. Create `src/steps/my_step.py` with a `run(context, config) -> dict` function.
2. Register it in `src/pipeline.py` by adding it to the step list and documenting which context keys it reads and writes.
3. Add any new config keys to `config.default.yml` with comments.

## Adding a config key

All config keys must appear in `config.default.yml` with a default value and an inline comment explaining the unit and valid range. Steps should call `config.get("section", {}).get("key", default)` rather than assuming the key exists.

## Running tests

```bash
pytest tests/
```

Integration tests in `tests/integration/` require a real video file at `tests/fixtures/sample.mp4`.

## Code style

- Python 3.11+. Use `str | None` instead of `Optional[str]`.
- No global state. Steps communicate only through the context dict.
- `emit_progress()` at the start (0.0) and end (1.0) of every step.
- FFmpeg commands via `utils/ffmpeg.py` helpers — never shell strings.
- Raise `ValueError` for invalid pipeline state; let FFmpeg errors propagate from `run_ffmpeg()`.
