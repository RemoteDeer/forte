"""One isolated process per video; the API supervisor enforces the wall-clock deadline."""

import logging
import sys
from pathlib import Path

from pydantic import ValidationError

from .analyzer import analyze
from .config import Settings
from .db import Store
from .rules import catalog
from .schemas import Violation
from .video import InvalidVideo, extract_frames, inspect_video

logger = logging.getLogger(__name__)


def process_job(settings: Settings, job_id: str):
    store = Store(settings.db_path)
    job = store.get(job_id)
    if not job or job["state"] != "running":
        return
    path = Path(job["path"])
    try:
        info = inspect_video(path)
        store.progress(job_id, "analyzing", 20)
        last_progress = 20

        def report_progress(fraction):
            nonlocal last_progress
            value = 20 + int(60 * max(0.0, min(1.0, fraction)))
            if value > last_progress:
                store.progress(job_id, "analyzing", value)
                last_progress = value

        output = analyze(
            path, settings.mode, settings.plugin, info.duration, on_progress=report_progress
        )
        store.progress(job_id, "extracting_evidence", 80)
        violations = []
        for detection in sorted(output.detections, key=lambda x: x.timecode_sec):
            if detection.timecode_sec >= info.duration:
                raise ValueError("ML returned a timecode outside the video")
            if detection.end_sec is not None and detection.end_sec > info.duration:
                raise ValueError("ML returned an episode range outside the video")
            rule = catalog().get(detection.rule_id)
            if rule is None:
                raise ValueError(f"Unknown rule_id: {detection.rule_id}")
            timestamps = detection.evidence_timestamps or [detection.timecode_sec]
            evidence = extract_frames(path, timestamps, info)
            # Include source in description for jury clients that ignore extra fields.
            description = (
                f"{detection.description}\nОснование для проверки: {rule.document}, "
                f"{rule.section}. {rule.url}\nОграничение: {rule.limitation}"
            )
            violations.append(
                Violation(
                    type=detection.type,
                    timecode_sec=detection.timecode_sec,
                    start_sec=detection.start_sec,
                    end_sec=detection.end_sec,
                    description=description,
                    evidence_frames=evidence,
                    rule=rule,
                    confidence=detection.confidence,
                    alternative_explanation=detection.alternative_explanation,
                    missing_data=detection.missing_data,
                ).model_dump()
            )
            store.progress(
                job_id,
                "extracting_evidence",
                80 + int(15 * len(violations) / len(output.detections)),
            )
        store.finish(
            job_id,
            {
                "verdict": "violation" if violations else "no_violation",
                "violations": violations,
                "duration_sec": info.duration,
                "limitations": [
                    *output.limitations,
                    "Результат — подсказка для проверки человеком, "
                    "а не юридическое или дисциплинарное заключение.",
                ],
            },
        )
    except InvalidVideo as exc:
        store.fail(job_id, "invalid_video", str(exc))
    except (ValidationError, ValueError, TypeError):
        logger.exception("Invalid model output for job %s", job_id)
        store.fail(
            job_id,
            "invalid_model_output",
            "Некорректный результат ML-модуля. Проверьте контракт и локальные логи.",
        )
    except Exception:
        logger.exception("Analysis failed for job %s", job_id)
        store.fail(
            job_id, "analysis_failed", "Ошибка локального ML-модуля. Проверьте логи сервера."
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    process_job(Settings.from_env(), sys.argv[1])
