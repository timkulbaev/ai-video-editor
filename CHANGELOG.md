# Changelog

All notable changes to ai-video-editor are documented here.

## v0.1.2 — 2026-02-25

### Fixed
- "Cut cut" restart phrases and other short isolated speech bursts are now reliably removed — new VAD-based short burst detection runs before segment merging, catching restart markers that Whisper skips.

### Removed
- Zoom punch-in feature (jump_cuts.py, face_detect.py, MediaPipe dependency) — disabled code removed entirely.

### Changed
- New config key `restarts.max_burst_duration_sec` (default 2.0) controls the short burst threshold.
- Pre-existing Russian filler word test fixture corrected (word duration was below min_filler_duration_sec threshold).

## v0.1.1 — 2026-02-24

### Fixed
- Smart hook crossfade now works reliably — hook clip extraction uses libx264 re-encode instead of stream copy, eliminating FFmpeg xfade timebase mismatch that caused hook prepend to silently fail on Apple QuickTime source videos.

### Changed
- Hook clip extraction uses input-side seek for better performance on long videos.
- CONTRIBUTING.md project structure updated with all 15 source files and corrected paths.
- pyproject.toml version aligned with CHANGELOG (was incorrectly set to 1.0.0).

## v0.1.0 — 2026-02-24

### Added
- **Core pipeline**: VAD-based silence removal (Silero), word-level transcription (faster-whisper large-v3), frame-accurate segment assembly via FFmpeg, and hardware encoding (VideoToolbox on macOS).
- **Restart phrase detection**: Removes entire VAD segments containing trigger phrases ("cut cut", "кат кат"). Falls back to repeated-sentence-start detection for implicit restarts.
- **Filler word removal**: Cuts filler words from English and Russian out of segments by splitting them around detected word boundaries.
- **Minimum silence gap merging**: Adjacent VAD segments separated by less than `min_gap_sec` (default 2.0 s) are merged so natural mid-sentence pauses are preserved.
- **Cut-point padding**: Every cut boundary is extended by `padding_sec` (default 0.5 s) on both sides; newly overlapping segments are merged automatically.
- **Audio enhancement**: Optional audio polish chain (denoise, highpass, de-esser, compression, loudness normalization to –14 LUFS). Disabled by default.
- **Smart hook**: Optional AI-generated YouTube hook intro via OpenRouter. Disabled by default.
- **YouTube chapters**: Optional AI-generated chapter timestamps via OpenRouter. Disabled by default.
- **LUT color grading**: Optional `.cube` LUT application. Disabled by default.
- **Face-centered crop**: Optional MediaPipe-based position smoothing. Enabled by default, skipped if MediaPipe is absent.
- **MCP server**: FastMCP server exposing `process_video`, `video_info`, and `list_models` tools for Claude Desktop integration.
- **CLI**: Typer-based CLI with `process`, `info`, and `models` commands plus JSON-line progress output.

### Technical
- VideoToolbox encoding uses `-b:v` bitrate (probed from input) instead of `-q:v` (unsupported by VideoToolbox).
- Segment extraction uses output-side `-ss` + `-t` + libx264 re-encode for frame-accurate cuts without keyframe-snapping content duplication.
- `torchaudio` dependency removed; PCM extraction uses stdlib `wave` + `struct.unpack`.
- `edit_stats.segments_removed` tracks only restart removals (not filler splits, which would produce negative values).
