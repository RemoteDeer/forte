"""Adapt the team's YOLO11 detector to the backend contract, with local weights only."""

import logging
import math
import os
from pathlib import Path

from .analyze_video import RULES
from .analyze_video import analyze as analyze_detections

ROOT = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)
DESCRIPTIONS = {
    "cash_unattended": (
        "На рабочей поверхности распознаны наличные, при этом человек в рабочей зоне "
        "не обнаружен не менее двух секунд. Проверьте, действительно ли деньги "
        "остались без присмотра."
    ),
    "service_abandoned": (
        "В кадре присутствует человек вне рабочей зоны, а в самой рабочей зоне человек "
        "не обнаружен не менее трёх секунд. Проверьте, продолжалось ли обслуживание клиента."
    ),
}


def model_path() -> Path:
    path = Path(os.getenv("FORTE_MODEL_PATH", "models/v0m_early.pt")).expanduser()
    return path if path.is_absolute() else ROOT / path


def available() -> bool:
    """Cheap preflight; the real validation is loading the model and analyzing a video."""
    from importlib.util import find_spec

    return model_path().is_file() and all(
        find_spec(name) is not None
        for name in ("torch", "torchvision", "ultralytics", "av")
    )


def convert_output(output: dict) -> dict:
    if output.get("error"):
        raise RuntimeError(f"YOLO analysis failed: {output['error']}")
    violations = output["violations"]
    expected = "violation" if violations else "no_violation"
    if output["verdict"] != expected:
        raise ValueError("YOLO verdict disagrees with detected episodes")
    detections = []
    for event in violations:
        kind = event["kind"]
        code, title, _ = RULES[kind]
        start, end = event["timecode_sec"], event["end_sec"]
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            raise ValueError("Invalid YOLO episode range")
        detections.append(
            {
                "type": title,
                "timecode_sec": start,
                "start_sec": start,
                "end_sec": end,
                "description": DESCRIPTIONS[kind],
                "rule_id": code,
                # Omit confidence: the source detector supplies no episode score.
                "evidence_timestamps": [start, (start + end) / 2],
                "alternative_explanation": (
                    "Человек мог быть перекрыт предметом или находиться вне зоны камеры; "
                    "назначение людей и факт обслуживания по детекции объектов не устанавливаются."
                ),
                "missing_data": [
                    "Подтверждение роли людей и контекста операции",
                    "Проверка применимости нормативной ссылки из ML-скрипта",
                ],
            }
        )
    limitations = [
        "YOLO11, ранние веса v0m_early.pt; качество на контрольной выборке не подтверждено.",
        (
            "Проверяются только наличные без присмотра и отсутствие человека в рабочей зоне; "
            "пересчёт банкнот, подлинность и остальные правила не распознаются."
        ),
        "Уверенность эпизода исходным алгоритмом не вычисляется; confidence не передаётся.",
        "Номера пунктов НБРК для ML01/ML02 переданы автором модели и требуют проверки.",
    ]
    if output.get("used_fallback_area"):
        limitations.append(
            "Счётчик банкнот и ноутбук не найдены; "
            "рабочая зона задана центральной нижней частью кадра."
        )
    return {"detections": detections, "limitations": limitations}


def analyze(video_path: str, *, on_progress=None, duration=None) -> dict:
    weights = model_path()
    if not weights.is_file():
        raise FileNotFoundError(f"Local YOLO weights missing: {weights}")
    # Disable automatic dependency downloads before importing Ultralytics.
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    os.environ.setdefault("YOLO_OFFLINE", "true")
    os.environ.setdefault(
        "YOLO_CONFIG_DIR",
        str(Path(os.getenv("FORTE_DATA_DIR", ROOT / "data")) / "ultralytics"),
    )
    import torch
    from ultralytics import YOLO, settings

    settings.update(
        {
            "sync": False,
            "clearml": False,
            "comet": False,
            "dvc": False,
            "mlflow": False,
            "raytune": False,
            "wandb": False,
        }
    )

    torch.set_num_threads(
        int(os.getenv("FORTE_ML_THREADS", min(4, os.cpu_count() or 1)))
    )
    fps = float(os.getenv("FORTE_ML_FPS", "3"))
    conf = float(os.getenv("FORTE_ML_CONF", "0.35"))
    imgsz = int(os.getenv("FORTE_ML_IMGSZ", "864"))
    if not 0 < fps <= 30 or not 0 < conf <= 1 or not 32 <= imgsz <= 2048:
        raise ValueError("Invalid ML sampling FPS, confidence threshold or image size")
    logger.info(
        "Loading YOLO weights %s; device=%s; fps=%s",
        weights.name,
        os.getenv("FORTE_ML_DEVICE", "cpu"),
        fps,
    )
    model = YOLO(str(weights))
    names = model.names.values() if isinstance(model.names, dict) else model.names
    if not {"person", "cash"}.issubset(set(names)):
        raise RuntimeError("YOLO model must contain the person and cash classes")
    output = analyze_detections(
        model,
        video_path,
        fps=fps,
        conf=conf,
        imgsz=imgsz,
        device=os.getenv("FORTE_ML_DEVICE", "cpu"),
        on_progress=on_progress,
        duration=duration,
    )
    return convert_output(output)
