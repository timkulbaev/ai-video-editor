"""MediaPipe face detection wrapper for face-centered crop positioning."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass
class FacePosition:
    """Normalized face center coordinates (0.0 to 1.0)."""
    cx: float  # horizontal center
    cy: float  # vertical center
    confidence: float


def detect_face_center(image_path: str | Path) -> FacePosition | None:
    """Detect the primary face in an image and return its normalized center.

    Returns None if no face is detected (caller falls back to center crop).
    Imports MediaPipe lazily so the rest of the tool works without it installed.
    """
    try:
        import mediapipe as mp
        import cv2
    except ImportError:
        # MediaPipe or OpenCV not installed — graceful fallback
        return None

    mp_face_detection = mp.solutions.face_detection

    img = cv2.imread(str(image_path))
    if img is None:
        return None

    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    with mp_face_detection.FaceDetection(
        model_selection=0, min_detection_confidence=0.5
    ) as detector:
        results = detector.process(rgb)

    if not results.detections:
        return None

    # Pick the detection with the highest confidence
    best = max(results.detections, key=lambda d: d.score[0])
    bb = best.location_data.relative_bounding_box

    cx = bb.xmin + bb.width / 2.0
    cy = bb.ymin + bb.height / 2.0

    return FacePosition(cx=cx, cy=cy, confidence=best.score[0])


def sample_face_positions(
    video_path: str | Path,
    sample_interval_sec: float = 5.0,
    duration_sec: float | None = None,
) -> list[FacePosition]:
    """Sample face positions from a video at regular intervals.

    Extracts frames via OpenCV and runs face detection on each.
    Returns a list of detected positions (may be shorter than expected if faces
    are not detected in some frames).

    Falls back to an empty list if OpenCV or MediaPipe are unavailable.
    """
    try:
        import cv2
    except ImportError:
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    total_sec = total_frames / fps if fps > 0 else 0.0
    if duration_sec is not None:
        total_sec = min(total_sec, duration_sec)

    positions: list[FacePosition] = []
    t = 0.0
    while t <= total_sec:
        frame_idx = int(t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            break

        # Detect face in this frame
        try:
            import mediapipe as mp
            mp_face_detection = mp.solutions.face_detection
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            with mp_face_detection.FaceDetection(
                model_selection=0, min_detection_confidence=0.5
            ) as detector:
                results = detector.process(rgb)
            if results.detections:
                best = max(results.detections, key=lambda d: d.score[0])
                bb = best.location_data.relative_bounding_box
                positions.append(
                    FacePosition(
                        cx=bb.xmin + bb.width / 2.0,
                        cy=bb.ymin + bb.height / 2.0,
                        confidence=best.score[0],
                    )
                )
        except Exception:
            pass  # Skip frame on any detection error

        t += sample_interval_sec

    cap.release()
    return positions


def average_face_position(positions: list[FacePosition]) -> FacePosition | None:
    """Return the average face position from a list of samples, or None if empty."""
    if not positions:
        return None
    cx = sum(p.cx for p in positions) / len(positions)
    cy = sum(p.cy for p in positions) / len(positions)
    conf = sum(p.confidence for p in positions) / len(positions)
    return FacePosition(cx=cx, cy=cy, confidence=conf)
