"""Backend adapter for the three-model package supplied on 18 October 2026."""

import logging
import math
import os
from importlib.util import find_spec
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)
WEIGHTS = ("forte_det.pt", "forte_door.pt", "forte_safe.pt")
RULE_IDS = {
    "cash_left": "ML02",
    "bag_left": "ML03",
    "laptop_unlocked": "ML04",
    "door_open": "ML05",
    "safe_open": "ML06",
    "previous_cash": "ML07",
}


def models_dir():
    path = Path(os.getenv("FORTE_MODEL_DIR", "models")).expanduser()
    return path if path.is_absolute() else ROOT / path


def available():
    return all((models_dir() / name).is_file() for name in WEIGHTS) and all(
        find_spec(name) is not None for name in ("torch", "torchvision", "ultralytics", "cv2")
    )


def convert_output(result):
    from .forte_service import RULES

    if result.get("status") != "done" or result.get("error"):
        raise RuntimeError(f"Forte analysis failed: {result.get('error', 'invalid status')}")
    events = result["violations"]
    if result["verdict"] != ("violation" if events else "no_violation"):
        raise ValueError("Forte verdict disagrees with detected events")
    by_title = {value[0]: kind for kind, value in RULES.items()}
    detections = []
    for event in events:
        kind = by_title[event["type"]]
        timestamp = event["timecode_sec"]
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("Invalid Forte event timestamp")
        timestamps = [frame["timestamp_sec"] for frame in event["evidence_frames"]]
        if not timestamps:
            raise ValueError("Forte event has no evidence timestamps")
        detections.append(
            {
                "type": event["type"],
                "timecode_sec": timestamp,
                "description": event["description"],
                "rule_id": RULE_IDS[kind],
                "evidence_timestamps": timestamps,
                "alternative_explanation": (
                    "Проверьте роль людей, перекрытия и контекст операции по исходному видео."
                ),
                "missing_data": [
                    "Подтверждение контекста операции и применимости нормативной ссылки"
                ],
            }
        )
    return {
        "detections": detections,
        "limitations": [
            "Forte service: локальные модели объектов, двери и сейфа; правила автора модели.",
            "Проверка документов, УФ-проверка и пересчёт в машинке не распознаются.",
            "Роли людей, факт нарушения и нормативные ссылки требуют ручной проверки.",
            "Первое событие каждого типа; границы и уверенность эпизода не вычисляются.",
        ],
    }


def analyze(video_path: str, *, on_progress=None, duration=None):
    directory = models_dir()
    for name in WEIGHTS:
        if not (directory / name).is_file():
            raise FileNotFoundError(f"Local Forte weights missing: {directory / name}")
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    os.environ.setdefault("YOLO_OFFLINE", "true")
    os.environ.setdefault(
        "YOLO_CONFIG_DIR",
        str(Path(os.getenv("FORTE_DATA_DIR", ROOT / "data")) / "ultralytics"),
    )
    import torch
    from ultralytics import settings

    from .forte_service import Analyzer

    settings.update(
        {key: False for key in ("sync", "clearml", "comet", "dvc", "mlflow", "raytune", "wandb")}
    )
    torch.set_num_threads(int(os.getenv("FORTE_ML_THREADS", min(4, os.cpu_count() or 1))))

    class ReportingAnalyzer(Analyzer):
        def frames(self, path):
            for timestamp, image in super().frames(path):
                yield timestamp, image
                if on_progress is not None and duration is not None and duration > 0:
                    on_progress(min(0.99, max(0.0, timestamp / duration)))

    engine = ReportingAnalyzer(directory, device=os.getenv("FORTE_ML_DEVICE", "cpu"))
    names = set(engine.det.names.values())
    if engine.det.task != "detect" or not {"person", "cash", "safe"}.issubset(names):
        raise ValueError("Unexpected Forte object detector task or class names")
    for classifier in (engine.door, engine.safe):
        if classifier.task != "classify" or "open" not in classifier.names.values():
            raise ValueError("Forte door/safe models must be open/closed classifiers")
    logger.info(
        "Forte models loaded from %s; detector classes=%s; device=%s; fps=2; conf=0.25; imgsz=864",
        directory,
        engine.det.names,
        engine.device,
    )
    result = engine.analyze(video_path)
    output = convert_output(result)
    if on_progress is not None:
        on_progress(1.0)
    logger.info("Forte verdict=%s; events=%s", result["verdict"], len(output["detections"]))
    return output
