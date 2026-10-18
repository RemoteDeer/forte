import base64
import math
from dataclasses import dataclass
from pathlib import Path

import cv2

from .schemas import EvidenceFrame


class InvalidVideo(Exception):
    pass


@dataclass(frozen=True)
class VideoInfo:
    duration: float
    fps: float
    frames: int


def inspect_video(path: Path) -> VideoInfo:
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not cap.isOpened() or not math.isfinite(fps) or fps <= 0:
            raise InvalidVideo("Не удалось открыть видео или определить частоту кадров.")
        if not math.isfinite(frames) or frames < 1:
            raise InvalidVideo("Видеодорожка отсутствует или повреждена.")
        ok, frame = cap.read()
        if not ok or frame is None:
            raise InvalidVideo("Не удалось декодировать первый кадр видео.")
        return VideoInfo(duration=frames / fps, fps=fps, frames=int(frames))
    finally:
        cap.release()


def extract_frames(path: Path, timestamps: list[float], info: VideoInfo) -> list[EvidenceFrame]:
    cap = cv2.VideoCapture(str(path))
    evidence = []
    try:
        for timestamp in timestamps:
            if not math.isfinite(timestamp) or not 0 <= timestamp < info.duration:
                raise ValueError("ML returned an evidence timestamp outside the video")
            index = min(int(timestamp * info.fps), info.frames - 1)
            if not cap.set(cv2.CAP_PROP_POS_FRAMES, index):
                raise InvalidVideo("Не удалось перейти к кадру-доказательству.")
            ok, frame = cap.read()
            if not ok or frame is None:
                raise InvalidVideo("Не удалось декодировать кадр-доказательство.")
            # Report actual decoded position, not an invented time from the model.
            actual_index = max(0, cap.get(cv2.CAP_PROP_POS_FRAMES) - 1)
            height, width = frame.shape[:2]
            if max(height, width) > 1280:
                factor = 1280 / max(height, width)
                frame = cv2.resize(frame, (round(width * factor), round(height * factor)))
            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if not ok:
                raise InvalidVideo("Не удалось сохранить JPEG-кадр.")
            evidence.append(
                EvidenceFrame(
                    timestamp_sec=round(actual_index / info.fps, 4),
                    image_base64=base64.b64encode(encoded).decode("ascii"),
                )
            )
    finally:
        cap.release()
    return evidence
