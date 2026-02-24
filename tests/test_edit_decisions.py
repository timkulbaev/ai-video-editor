"""Tests for edit decision logic — segment computation, restart detection, filler removal."""

from __future__ import annotations

import pytest

from src.steps.edit_decisions import (
    run,
    _remove_restart_phrases,
    _remove_fillers,
    _remove_short_bursts,
    _ranges_overlap,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_word(word: str, start: float, end: float) -> dict:
    return {"word": word, "start": start, "end": end, "probability": 0.99}


def _make_segment(text: str, start: float, end: float, words: list[dict] | None = None) -> dict:
    return {"text": text, "start": start, "end": end, "words": words or []}


def _make_keep_seg(start: float, end: float) -> dict:
    return {"start": start, "end": end}


DEFAULT_CONFIG = {
    "restarts": {
        "enabled": True,
        "trigger_phrases": ["cut cut", "кат кат"],
        "detect_repeated_starts": True,
    },
    "fillers": {
        "enabled": True,
        "words": {
            "en": ["um", "uh", "like", "you know"],
            "ru": ["ну", "типа", "вот"],
        },
    },
}


# ---------------------------------------------------------------------------
# _ranges_overlap
# ---------------------------------------------------------------------------

class TestRangesOverlap:
    def test_complete_overlap(self):
        assert _ranges_overlap(0.0, 10.0, 2.0, 5.0) is True

    def test_partial_overlap_at_start(self):
        assert _ranges_overlap(1.0, 5.0, 0.0, 3.0) is True

    def test_partial_overlap_at_end(self):
        assert _ranges_overlap(1.0, 5.0, 4.0, 8.0) is True

    def test_no_overlap_adjacent(self):
        # Ranges touch but don't overlap (a_end == b_start)
        assert _ranges_overlap(0.0, 5.0, 5.0, 10.0) is False

    def test_no_overlap_gap(self):
        assert _ranges_overlap(0.0, 3.0, 5.0, 10.0) is False

    def test_reversed_ranges(self):
        assert _ranges_overlap(5.0, 10.0, 0.0, 3.0) is False


# ---------------------------------------------------------------------------
# _remove_short_bursts
# ---------------------------------------------------------------------------

class TestRemoveShortBursts:
    def test_remove_short_bursts_filters_short_segments(self):
        segments = [
            {"start": 0.0, "end": 0.5},   # short burst (0.5s < 2.0s threshold)
            {"start": 2.0, "end": 7.0},   # long segment (5.0s) — should survive
            {"start": 8.0, "end": 9.5},   # short burst (1.5s < 2.0s threshold)
        ]
        kept, burst_count = _remove_short_bursts(segments, max_duration_sec=2.0)
        assert len(kept) == 1
        assert kept[0]["start"] == 2.0
        assert kept[0]["end"] == 7.0
        assert burst_count == 2


# ---------------------------------------------------------------------------
# _remove_fillers
# ---------------------------------------------------------------------------

class TestRemoveFillers:
    def test_no_fillers_in_transcript(self):
        segments = [_make_keep_seg(0.0, 5.0)]
        transcript = [_make_segment("Hello world", 0.0, 5.0, [
            _make_word("Hello", 0.0, 0.5),
            _make_word("world", 0.5, 1.0),
        ])]
        result, count = _remove_fillers(
            segments, transcript, {"words": {"en": ["um"], "ru": []}}
        )
        assert result == segments
        assert count == 0

    def test_single_filler_at_start_splits_segment(self):
        # "um Hello world" — um should be removed, leaving Hello world
        segments = [_make_keep_seg(0.0, 3.0)]
        transcript = [_make_segment("um Hello world", 0.0, 3.0, [
            _make_word("um", 0.0, 0.3),
            _make_word("Hello", 0.3, 1.0),
            _make_word("world", 1.0, 2.0),
        ])]
        result, count = _remove_fillers(
            segments, transcript, {"words": {"en": ["um"], "ru": []}}
        )
        assert count == 1
        # Only the tail after "um" (0.3 to 3.0) should be kept
        assert len(result) == 1
        assert result[0]["start"] == pytest.approx(0.3)
        assert result[0]["end"] == pytest.approx(3.0)

    def test_single_filler_in_middle_creates_two_segments(self):
        # "Hello um world" — um removed, leaving "Hello" and "world"
        segments = [_make_keep_seg(0.0, 3.0)]
        transcript = [_make_segment("Hello um world", 0.0, 3.0, [
            _make_word("Hello", 0.0, 0.5),
            _make_word("um", 0.5, 0.8),
            _make_word("world", 0.8, 1.5),
        ])]
        result, count = _remove_fillers(
            segments, transcript, {"words": {"en": ["um"], "ru": []}}
        )
        assert count == 1
        assert len(result) == 2
        assert result[0]["start"] == pytest.approx(0.0)
        assert result[0]["end"] == pytest.approx(0.5)
        assert result[1]["start"] == pytest.approx(0.8)
        assert result[1]["end"] == pytest.approx(3.0)

    def test_multiple_fillers_removed(self):
        # "um hello uh world" — both fillers removed
        segments = [_make_keep_seg(0.0, 4.0)]
        transcript = [_make_segment("um hello uh world", 0.0, 4.0, [
            _make_word("um", 0.0, 0.3),
            _make_word("hello", 0.3, 1.0),
            _make_word("uh", 1.0, 1.3),
            _make_word("world", 1.3, 2.0),
        ])]
        result, count = _remove_fillers(
            segments, transcript, {"words": {"en": ["um", "uh"], "ru": []}}
        )
        assert count == 2
        assert len(result) == 2

    def test_russian_filler_removed(self):
        segments = [_make_keep_seg(0.0, 3.0)]
        transcript = [_make_segment("ну хорошо", 0.0, 3.0, [
            _make_word("ну", 0.0, 0.35),  # 0.35s duration — above 0.3s min_filler_duration_sec default
            _make_word("хорошо", 0.35, 1.0),
        ])]
        result, count = _remove_fillers(
            segments, transcript, {"words": {"en": [], "ru": ["ну"]}}
        )
        assert count == 1

    def test_filler_outside_segment_not_removed(self):
        # Filler is in transcript but outside our segment time range
        segments = [_make_keep_seg(5.0, 10.0)]
        transcript = [_make_segment("um hello", 0.0, 3.0, [
            _make_word("um", 0.0, 0.3),
            _make_word("hello", 0.3, 1.0),
        ])]
        result, count = _remove_fillers(
            segments, transcript, {"words": {"en": ["um"], "ru": []}}
        )
        assert result == segments
        assert count == 0

    def test_empty_filler_list_no_changes(self):
        segments = [_make_keep_seg(0.0, 5.0)]
        transcript = [_make_segment("um uh like", 0.0, 5.0)]
        result, count = _remove_fillers(
            segments, transcript, {"words": {"en": [], "ru": []}}
        )
        assert result == segments
        assert count == 0


# ---------------------------------------------------------------------------
# _remove_restart_phrases
# ---------------------------------------------------------------------------

class TestRemoveRestartPhrases:
    def test_cut_cut_removes_preceding_segment(self):
        # Segment 0:0-5 is the failed attempt, "cut cut" is at 5-6
        # The full segment at 0-6 should be removed
        segments = [
            _make_keep_seg(0.0, 5.0),
            _make_keep_seg(6.0, 12.0),
        ]
        transcript = [
            _make_segment("some content cut cut", 0.0, 6.0, [
                _make_word("some", 0.0, 0.3),
                _make_word("content", 0.3, 0.8),
                _make_word("cut", 5.0, 5.3),
                _make_word("cut", 5.4, 5.7),
            ]),
            _make_segment("restart here", 6.0, 12.0, [
                _make_word("restart", 6.0, 6.5),
                _make_word("here", 6.5, 7.0),
            ]),
        ]
        config = {
            "trigger_phrases": ["cut cut"],
            "detect_repeated_starts": False,
        }
        result = _remove_restart_phrases(segments, transcript, config)
        # The first segment (0-5) overlaps the removal range [0, 5.7] -> removed
        # The second segment (6-12) should survive
        removed_starts = {s["start"] for s in result}
        assert 0.0 not in removed_starts
        assert 6.0 in removed_starts

    def test_no_trigger_phrase_no_removal(self):
        segments = [_make_keep_seg(0.0, 5.0), _make_keep_seg(5.0, 10.0)]
        transcript = [
            _make_segment("hello world", 0.0, 5.0, [
                _make_word("hello", 0.0, 0.4),
                _make_word("world", 0.4, 1.0),
            ])
        ]
        config = {"trigger_phrases": ["cut cut"], "detect_repeated_starts": False}
        result = _remove_restart_phrases(segments, transcript, config)
        assert len(result) == 2

    def test_repeated_sentence_start_removed(self):
        # Two segments starting with the same 3 words -> first is a restart
        segments = [
            _make_keep_seg(0.0, 3.0),   # first attempt
            _make_keep_seg(4.0, 10.0),  # clean take
        ]
        transcript = [
            _make_segment("So today we", 0.0, 3.0, [
                _make_word("So", 0.0, 0.2),
                _make_word("today", 0.2, 0.5),
                _make_word("we", 0.5, 0.7),
            ]),
            _make_segment("So today we talk about", 4.0, 10.0, [
                _make_word("So", 4.0, 4.2),
                _make_word("today", 4.2, 4.6),
                _make_word("we", 4.6, 4.9),
                _make_word("talk", 4.9, 5.2),
                _make_word("about", 5.2, 5.5),
            ]),
        ]
        config = {"trigger_phrases": [], "detect_repeated_starts": True}
        result = _remove_restart_phrases(segments, transcript, config)
        # First segment (0-3) is a restart -> should be removed
        starts = {s["start"] for s in result}
        assert 0.0 not in starts
        assert 4.0 in starts

    def test_cyrillic_trigger_phrase(self):
        segments = [_make_keep_seg(0.0, 5.0), _make_keep_seg(6.0, 10.0)]
        transcript = [
            _make_segment("кат кат", 4.5, 5.0, [
                _make_word("кат", 4.5, 4.7),
                _make_word("кат", 4.8, 5.0),
            ]),
        ]
        config = {"trigger_phrases": ["кат кат"], "detect_repeated_starts": False}
        result = _remove_restart_phrases(segments, transcript, config)
        starts = {s["start"] for s in result}
        # Removal range is [max(0, 4.5-5), 5.0] = [0, 5.0] -> overlaps first segment
        assert 0.0 not in starts
        assert 6.0 in starts


# ---------------------------------------------------------------------------
# run() — full pipeline step
# ---------------------------------------------------------------------------

class TestRunStep:
    def test_run_returns_keep_segments_and_stats(self):
        context = {
            "speech_segments": [
                {"start": 0.0, "end": 5.0},
                {"start": 6.0, "end": 12.0},
                {"start": 13.0, "end": 20.0},
            ],
            "transcript": [],
        }
        result = run(context, DEFAULT_CONFIG)
        assert "keep_segments" in result
        assert "edit_stats" in result

    def test_run_keep_segments_format(self):
        context = {
            "speech_segments": [{"start": 0.0, "end": 5.0}],
            "transcript": [],
        }
        result = run(context, DEFAULT_CONFIG)
        seg = result["keep_segments"][0]
        assert "start" in seg
        assert "end" in seg

    def test_run_fillers_and_restarts_disabled(self):
        config = dict(DEFAULT_CONFIG)
        config["restarts"] = {"enabled": False}
        config["fillers"] = {"enabled": False}
        context = {
            "speech_segments": [{"start": 0.0, "end": 10.0}],
            "transcript": [],
        }
        result = run(context, config)
        assert len(result["keep_segments"]) == 1

    def test_run_empty_speech_segments(self):
        context = {"speech_segments": [], "transcript": []}
        result = run(context, DEFAULT_CONFIG)
        assert result["keep_segments"] == []
        assert result["edit_stats"]["segments_removed"] == 0

    def test_run_stats_fillers_counted(self):
        context = {
            "speech_segments": [{"start": 0.0, "end": 5.0}],
            "transcript": [
                _make_segment("um hello world", 0.0, 5.0, [
                    _make_word("um", 0.0, 0.3),
                    _make_word("hello", 0.3, 1.0),
                    _make_word("world", 1.0, 2.0),
                ])
            ],
        }
        result = run(context, DEFAULT_CONFIG)
        assert result["edit_stats"]["fillers_removed"] >= 1
