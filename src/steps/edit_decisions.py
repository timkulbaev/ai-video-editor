"""Compute the final list of segments to keep.

Combines:
  - Speech segments from Silero VAD (silence removal)
  - Restart phrase detection ("cut cut", "кат кат", repeated sentence starts)
  - Filler word removal (configurable word lists)
"""

from __future__ import annotations

from typing import Any

from ..utils.json_output import emit_progress


def run(context: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Compute the final keep-segment list by applying all editing rules.

    Args:
        context: Pipeline state. Reads:
            - "speech_segments": [{start, end}, ...] from Silero VAD
            - "transcript": [{text, start, end, words: [{word, start, end, probability}]}, ...]
            - "total_duration": float — video duration in seconds (for padding clamp)
        config: Full pipeline config. Reads config["silence"], config["restarts"],
                config["fillers"], config["video"]["zoom_punch"].

    Returns:
        {
            "keep_segments": [{"start": float, "end": float, "zoom": bool, "zoom_factor": float}],
            "edit_stats": {"silence_removed_sec": float, "segments_removed": int,
                           "restarts_removed": int, "fillers_removed": int}
        }
    """
    emit_progress("analysis", "edit_decisions", 0.0, "Computing edit decisions...")

    speech_segments: list[dict] = context.get("speech_segments", [])
    transcript: list[dict] = context.get("transcript", [])

    # Merge adjacent VAD segments separated by a short gap.
    # Natural pauses shorter than min_gap_sec are preserved rather than cut.
    # This runs first, before restart/filler removal, so those steps see
    # already-merged segments.
    silence_cfg = config.get("silence", {})
    min_gap_sec: float = silence_cfg.get("min_gap_sec", 2.0)
    speech_segments = _merge_close_segments(speech_segments, min_gap_sec)

    keep_segments = [
        {"start": s["start"], "end": s["end"], "zoom": False, "zoom_factor": 1.05}
        for s in speech_segments
    ]

    edit_stats = {
        "silence_removed_sec": 0.0,
        "segments_removed": 0,
        "restarts_removed": 0,
        "fillers_removed": 0,
    }

    # Remove restart phrases
    restarts_cfg = config.get("restarts", {})
    if restarts_cfg.get("enabled", True):
        before = len(keep_segments)
        keep_segments = _remove_restart_phrases(keep_segments, transcript, restarts_cfg)
        removed = before - len(keep_segments)
        edit_stats["restarts_removed"] = removed

    # Remove filler words
    fillers_cfg = config.get("fillers", {})
    if fillers_cfg.get("enabled", True):
        keep_segments, filler_count = _remove_fillers(keep_segments, transcript, fillers_cfg)
        edit_stats["fillers_removed"] = filler_count

    # Apply padding around every cut point and merge any newly-overlapping segments.
    # This runs last — after restart removal and filler removal — so padding is applied
    # to the final cut list, not to intermediate results.
    padding_sec: float = silence_cfg.get("padding_sec", 0.5)
    total_duration: float = context.get("total_duration", float("inf"))
    if padding_sec > 0:
        keep_segments = _apply_padding(keep_segments, padding_sec, total_duration)

    # Compute how much time was removed vs. original speech
    original_sec = sum(s["end"] - s["start"] for s in speech_segments)
    kept_sec = sum(s["end"] - s["start"] for s in keep_segments)
    edit_stats["silence_removed_sec"] = round(max(0.0, original_sec - kept_sec), 2)
    # segments_removed tracks restart-detection drops only.
    # Filler removal splits segments (not drops) so must not be subtracted — doing so
    # causes negative values when fillers split more segments than restarts removed.
    edit_stats["segments_removed"] = edit_stats["restarts_removed"]

    # Apply alternating zoom punch-in on consecutive cut points
    zoom_cfg = config.get("video", {}).get("zoom_punch", {})
    if zoom_cfg.get("enabled", True):
        zoom_factor = zoom_cfg.get("zoom_factor", 1.05)
        for i, seg in enumerate(keep_segments):
            if i % 2 == 1:  # odd-indexed segments get zoom to mask jump cut
                seg["zoom"] = True
                seg["zoom_factor"] = zoom_factor

    emit_progress(
        "analysis",
        "edit_decisions",
        1.0,
        f"Edit decisions: keeping {len(keep_segments)} segments, "
        f"removed {edit_stats['restarts_removed']} restarts, "
        f"{edit_stats['fillers_removed']} fillers",
    )

    return {"keep_segments": keep_segments, "edit_stats": edit_stats}


def _merge_close_segments(segments: list[dict], min_gap_sec: float) -> list[dict]:
    """Merge adjacent speech segments whose gap is smaller than min_gap_sec.

    Short pauses (e.g. speaker taking a breath mid-sentence) should not be cut.
    Merging preserves the silence between the original VAD segments by spanning
    from the first segment's start to the last merged segment's end.

    Example with min_gap_sec=2.0:
        [0.0-5.0], [5.8-10.0], [11.5-15.0]
        gap(0→1) = 0.8s < 2.0 → merge → [0.0-10.0]
        gap(1→2) = 1.5s < 2.0 → merge → [0.0-15.0]
    """
    if not segments or min_gap_sec <= 0:
        return segments

    merged: list[dict] = []
    current = dict(segments[0])

    for next_seg in segments[1:]:
        gap = next_seg["start"] - current["end"]
        if gap < min_gap_sec:
            # Extend current segment to cover the gap and the next segment
            current["end"] = next_seg["end"]
        else:
            merged.append(current)
            current = dict(next_seg)

    merged.append(current)
    return merged


def _apply_padding(
    segments: list[dict],
    padding_sec: float,
    total_duration: float,
) -> list[dict]:
    """Extend each segment by padding_sec on both sides, then merge overlaps.

    Padding provides breathing room at cut points so transitions don't feel abrupt.
    After expanding, adjacent segments that now overlap (padded end >= next start)
    are merged into one to avoid duplicate frames.

    Args:
        segments: Final keep_segments list after all editing.
        padding_sec: Seconds to add before start and after end of each segment.
        total_duration: Video duration used to clamp segment ends. If unknown,
                        pass float("inf") and FFmpeg will handle out-of-range times.
    """
    if not segments:
        return segments

    # Expand each segment
    padded = []
    for seg in segments:
        padded.append({
            **seg,
            "start": max(0.0, seg["start"] - padding_sec),
            "end": min(total_duration, seg["end"] + padding_sec),
        })

    # Merge any segments that now overlap after expansion
    merged: list[dict] = []
    current = dict(padded[0])
    for next_seg in padded[1:]:
        if next_seg["start"] <= current["end"]:
            # Overlapping — extend current to cover next
            current["end"] = max(current["end"], next_seg["end"])
        else:
            merged.append(current)
            current = dict(next_seg)
    merged.append(current)
    return merged


def _remove_restart_phrases(
    segments: list[dict],
    transcript: list[dict],
    config: dict,
) -> list[dict]:
    """Remove segments containing restart trigger phrases or repeated sentence starts.

    Trigger phrase strategy: remove the ENTIRE speech segment that contains the
    trigger word (e.g. "cut cut" / "кат кат"). Each speech segment represents
    one continuous take — if the speaker said the trigger phrase anywhere in the
    segment, the whole take was a failed attempt and should go.

    Repeated sentence start strategy: unchanged — remove the earlier of two
    consecutive transcript segments that share the same first 3 words.
    """
    trigger_phrases = [p.lower() for p in config.get("trigger_phrases", ["cut cut", "кат кат"])]
    detect_repeated = config.get("detect_repeated_starts", True)

    all_words = []
    for seg in transcript:
        all_words.extend(seg.get("words", []))

    # Build the set of segment indices to drop
    drop_segment_indices: set[int] = set()

    # Explicit trigger phrases — drop the whole speech segment containing the trigger
    for phrase in trigger_phrases:
        phrase_words = phrase.split()
        n = len(phrase_words)
        for i in range(len(all_words) - n + 1):
            window = [w["word"].strip().lower().strip(".,!?") for w in all_words[i : i + n]]
            if window == phrase_words:
                trigger_time = all_words[i]["start"]
                # Find the speech segment that contains this trigger word
                for idx, seg in enumerate(segments):
                    if seg["start"] <= trigger_time <= seg["end"]:
                        drop_segment_indices.add(idx)
                        break

    # Collect time ranges to remove from repeated sentence starts (still range-based)
    repeated_ranges: list[tuple[float, float]] = []
    if detect_repeated:
        sentence_starts: list[tuple[str, float, float]] = []
        for seg in transcript:
            words = seg.get("words", [])
            if len(words) >= 3:
                key = " ".join(w["word"].strip().lower() for w in words[:3])
                sentence_starts.append((key, seg["start"], seg["end"]))

        for i in range(1, len(sentence_starts)):
            prev_key, prev_start, prev_end = sentence_starts[i - 1]
            curr_key, _, _ = sentence_starts[i]
            if prev_key == curr_key:
                repeated_ranges.append((prev_start, prev_end))

    return [
        seg for idx, seg in enumerate(segments)
        if idx not in drop_segment_indices
        and not any(
            _ranges_overlap(seg["start"], seg["end"], r_start, r_end)
            for r_start, r_end in repeated_ranges
        )
    ]


def _remove_fillers(
    segments: list[dict],
    transcript: list[dict],
    config: dict,
) -> tuple[list[dict], int]:
    """Remove filler words by splitting/trimming segments around them.

    Filler words shorter than min_filler_duration_sec are skipped — they are
    too brief to cut cleanly and would produce jarring micro-gaps.

    Returns (updated_segments, filler_word_count_removed).
    """
    filler_words_en = {w.lower() for w in config.get("words", {}).get("en", [])}
    filler_words_ru = {w.lower() for w in config.get("words", {}).get("ru", [])}
    all_fillers = filler_words_en | filler_words_ru
    min_duration: float = config.get("min_filler_duration_sec", 0.3)

    if not all_fillers:
        return segments, 0

    # Collect filler word time ranges from transcript, skipping very short ones
    filler_ranges: list[tuple[float, float]] = []
    for seg in transcript:
        for word in seg.get("words", []):
            clean = word["word"].strip().lower().strip(".,!?")
            if clean in all_fillers:
                duration = word["end"] - word["start"]
                if duration >= min_duration:
                    filler_ranges.append((word["start"], word["end"]))

    if not filler_ranges:
        return segments, 0

    filler_count = 0
    result: list[dict] = []

    for seg in segments:
        inner_fillers = [
            (fs, fe) for fs, fe in filler_ranges
            if fs >= seg["start"] and fe <= seg["end"]
        ]

        if not inner_fillers:
            result.append(seg)
            continue

        filler_count += len(inner_fillers)
        current_start = seg["start"]

        for fs, fe in sorted(inner_fillers, key=lambda x: x[0]):
            if current_start < fs:
                result.append({
                    "start": current_start,
                    "end": fs,
                    "zoom": seg["zoom"],
                    "zoom_factor": seg["zoom_factor"],
                })
            current_start = fe

        # Tail after last filler
        if current_start < seg["end"]:
            result.append({
                "start": current_start,
                "end": seg["end"],
                "zoom": seg["zoom"],
                "zoom_factor": seg["zoom_factor"],
            })

    return result, filler_count


def _ranges_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    """Return True if two time ranges overlap."""
    return a_start < b_end and b_start < a_end
