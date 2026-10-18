"""Contract example only. Copy to inference.py and replace with real local inference.

This module is deliberately NOT the default plugin. No dummy no_violation fallback.
"""


def analyze(video_path: str) -> dict:
    """Load local weights, analyze video_path and return the documented structure.

    Example return value for a real observed event:
    {
        "detections": [{
            "type": "Пересчёт после ухода клиента",
            "timecode_sec": 12.4,
            "start_sec": 10.0,
            "end_sec": 15.0,
            "description": "Клиент покидает зону, после чего кассир начинает пересчёт.",
            "rule_id": "R02",
            "confidence": 0.85,
            "evidence_timestamps": [10.0, 12.4],
            "alternative_explanation": "Возможно, это повторный внутренний пересчёт.",
            "missing_data": ["Подтверждение типа операции"]
        }],
        "limitations": []
    }

    A valid no-detection result is {"detections": [], "limitations": []}.
    Raise an exception if the model cannot analyze the video; never return [] on failure.
    """
    raise NotImplementedError("Connect the team's local ML model; see docs/ML_CONTRACT.md")
