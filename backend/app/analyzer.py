import importlib
import importlib.util
import inspect
from pathlib import Path

from .schemas import ModelOutput


def plugin_available(spec: str) -> bool:
    module, separator, function = spec.partition(":")
    if not separator or not function:
        return False
    try:
        if importlib.util.find_spec(module) is None:
            return False
        if module in {"ml.inference", "ml.service_inference"}:
            return importlib.import_module(module).available()
        return True
    except (ImportError, ValueError, AttributeError):
        return False


def analyze(path: Path, mode: str, plugin: str, duration: float, on_progress=None) -> ModelOutput:
    if mode == "demo":
        # Explicit fixture, never presented as model inference.
        return ModelOutput.model_validate(
            {
                "detections": [
                    {
                        "type": "Пересчёт не наблюдается",
                        "timecode_sec": min(1.0, duration / 2),
                        "description": "Пример: деньги убраны без видимого пересчёта.",
                        "rule_id": "R01",
                        "confidence": 0.0,
                        "alternative_explanation": "Это заранее заданный тестовый результат.",
                        "missing_data": ["Результат реальной ML-модели"],
                    }
                ]
                + (
                    [
                        {
                            "type": "Пересчёт после ухода клиента",
                            "timecode_sec": 4.0,
                            "description": "Пример: пересчёт начат после ухода клиента.",
                            "rule_id": "R02",
                            "confidence": 0.0,
                            "alternative_explanation": "Искусственный результат DEMO.",
                            "missing_data": ["Результат реальной ML-модели"],
                        }
                    ]
                    if duration > 4
                    else []
                ),
                "limitations": [
                    "DEMO: результат искусственный; не использовать для оценки качества."
                ],
            }
        )
    module_name, _, callable_name = plugin.partition(":")
    function = getattr(importlib.import_module(module_name), callable_name)
    # Existing one-argument plugins continue to work without progress reporting.
    parameters = inspect.signature(function).parameters
    kwargs = {}
    if "on_progress" in parameters:
        kwargs["on_progress"] = on_progress
    if "duration" in parameters:
        kwargs["duration"] = duration
    output = function(str(path), **kwargs)
    if inspect.isawaitable(output):
        raise TypeError("ML callable must be synchronous: def analyze(video_path: str) -> dict")
    return ModelOutput.model_validate(output)
