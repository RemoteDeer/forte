"""Deterministic adapters for integration tests; not application models."""

import time


def no_detections(video_path):
    return {"detections": [], "limitations": ["Test adapter"]}


def service_candidates(video_path):
    from ml.forte_service import RULES
    from ml.service_inference import convert_output

    return convert_output(
        {
            "status": "done",
            "verdict": "violation",
            "violations": [
                {
                    "type": title,
                    "timecode_sec": 0.2,
                    "description": why,
                    "rule": rule,
                    "evidence_frames": [{"timestamp_sec": 0.2}, {"timestamp_sec": 1.2}],
                }
                for title, why, rule in RULES.values()
            ],
        }
    )


def ml_candidates(video_path):
    from ml.inference import convert_output

    return convert_output(
        {
            "verdict": "violation",
            "violations": [
                {"kind": kind, "timecode_sec": 0.2, "end_sec": 4.0}
                for kind in ("cash_unattended", "service_abandoned")
            ],
        }
    )


def multiple(video_path):
    return {
        "detections": [
            {
                "type": "Первый эпизод",
                "timecode_sec": 0.2,
                "start_sec": 0.1,
                "end_sec": 0.6,
                "description": "Наблюдение A",
                "rule_id": "R01",
                "confidence": 0.8,
                "evidence_timestamps": [0.1, 0.2],
            },
            {
                "type": "Второй эпизод",
                "timecode_sec": 0.8,
                "description": "Наблюдение B",
                "rule_id": "R02",
                "confidence": 0.9,
            },
        ]
    }


def wrong_time(video_path):
    return {
        "detections": [
            {
                "type": "Test",
                "timecode_sec": 10000,
                "description": "Invalid",
                "rule_id": "R01",
                "confidence": 0.8,
            }
        ]
    }


def range_outside_video(video_path):
    return {
        "detections": [
            {
                "type": "Test",
                "timecode_sec": 0.2,
                "start_sec": 0.1,
                "end_sec": 100,
                "description": "Invalid",
                "rule_id": "R01",
                "confidence": 0.8,
            }
        ]
    }


def unknown_rule(video_path):
    return {
        "detections": [
            {
                "type": "Test",
                "timecode_sec": 0.2,
                "description": "Invalid",
                "rule_id": "UNKNOWN",
                "confidence": 0.8,
            }
        ]
    }


def wrong_evidence(video_path):
    return {
        "detections": [
            {
                "type": "Test",
                "timecode_sec": 0.2,
                "description": "Invalid",
                "rule_id": "R01",
                "confidence": 0.8,
                "evidence_timestamps": [-1],
            }
        ]
    }


def broken(video_path):
    raise RuntimeError("Private model failure")


def hangs(video_path):
    time.sleep(30)
    return {"detections": []}
