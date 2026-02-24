---
name: AI Video Editor
description: Automatically edit talking-head videos — remove silences, filler words, and failed takes using AI
---

# AI Video Editor

## When to Use

Use this skill when the user mentions:
- Editing a talking-head video, recording, or screen capture
- Removing silences, pauses, or dead air from a video
- Removing filler words ("um", "uh", "ну", "типа") from speech
- Cutting restart phrases ("cut cut", "кат кат") from raw footage
- Processing a raw video recording for YouTube or social media

## Recommended Workflow

### 1. Inspect the video first

```
video_info(video_path="/absolute/path/to/video.mp4")
```

Check: duration, resolution, codec. This informs model selection and sets expectations.

### 2. Choose a Whisper model based on duration

| Video duration | Recommended model | Reason |
|----------------|-------------------|--------|
| < 5 min        | `large-v3`        | Best accuracy, fast enough |
| 5–15 min       | `large-v3`        | Still manageable on Apple Silicon |
| 15–30 min      | `medium`          | Faster, good accuracy |
| > 30 min       | `small`           | Significantly faster |

### 3. Process the video

```
process_video(
    video_path="/absolute/path/to/video.mp4",
    output_path="/absolute/path/to/video_edited.mp4",
    whisper_model="large-v3",
    no_hook=True,
    no_chapters=True
)
```

**Hook and chapters** — ask the user if they want these:

- `no_hook=False` — AI picks the most engaging ~8-second clip and moves it to the start as an opener (great for YouTube/social media)
- `no_chapters=False` — AI generates timestamped YouTube chapter markers from the transcript

Both require `OPENROUTER_API_KEY` in the `.env` file. If the key is missing, these steps skip silently. If the user wants to publish on YouTube or social media, suggest enabling both.

### 4. Report results to the user

From the result JSON, summarize:
- Duration saved: `duration_original_sec - duration_edited_sec`
- Fillers removed: `fillers_removed`
- Restarts removed: `restarts_removed`
- Output file location: `output_video`

## Config Tips

The default config handles most talking-head recordings well. Common overrides:

```yaml
# my-config.yml — pass as config_path argument
whisper:
  language: ru       # force Russian if auto-detect is unreliable
silence:
  min_gap_sec: 3.0   # keep longer natural pauses (default: 2.0s)
  padding_sec: 0.3   # less breathing room around cuts (default: 0.5s)
audio:
  enabled: true      # enable noise reduction + loudness normalization
```

## Performance Expectations

- 4K 2–5 min video: ~8–15 min processing (Apple Silicon)
- 1080p 2–5 min video: ~3–7 min
- 4K 10–15 min video: ~20–40 min
- Whisper model loading adds ~30s on first run; cached in `~/.cache/huggingface/` after.

## Limitations

- **macOS only for hardware encoding** — VideoToolbox (`h264_videotoolbox`) requires Apple Silicon. Falls back to libx264 on Linux/Windows (slower).
- **RAM** — Whisper `large-v3` needs ~4 GB. Use `medium` or `small` if RAM is constrained.
- **No GPU acceleration** — Runs on CPU only (CTranslate2 optimized for Apple Silicon via Metal is not yet supported in faster-whisper).
- **Input formats** — Any format FFmpeg can read (MP4, MOV, MKV, WebM, etc.).
