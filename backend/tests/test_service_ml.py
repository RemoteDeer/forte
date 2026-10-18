import pytest

from backend.app.analyzer import plugin_available
from backend.app.rules import catalog
from backend.app.schemas import ModelOutput
from ml.forte_service import RULES, Analyzer
from ml.service_inference import RULE_IDS, WEIGHTS, analyze, convert_output


def event(kind, time=1.5):
    title, why, rule = RULES[kind]
    return {
        "type": title,
        "timecode_sec": time,
        "description": why,
        "rule": rule,
        "evidence_frames": [{"timestamp_sec": time}, {"timestamp_sec": time + 1}],
    }


def test_all_six_service_events_preserve_type_time_and_evidence():
    raw = {"status": "done", "verdict": "violation", "violations": [event(k) for k in RULES]}
    parsed = ModelOutput.model_validate(convert_output(raw))
    assert len(parsed.detections) == 6
    assert {d.rule_id for d in parsed.detections} == set(RULE_IDS.values())
    for detection, source in zip(parsed.detections, raw["violations"], strict=True):
        assert detection.type == source["type"]
        assert detection.description == source["description"]
        assert detection.timecode_sec == source["timecode_sec"]
        assert detection.evidence_timestamps == [1.5, 2.5]
        assert detection.rule_id in catalog()
        assert detection.confidence is None
        assert detection.start_sec is None  # The source returns point events, not ranges.


@pytest.mark.parametrize("missing", WEIGHTS)
def test_all_three_local_weights_are_required(monkeypatch, tmp_path, missing):
    for name in WEIGHTS:
        if name != missing:
            (tmp_path / name).write_bytes(b"placeholder")
    monkeypatch.setenv("FORTE_MODEL_DIR", str(tmp_path))
    assert not plugin_available("ml.service_inference:analyze")
    with pytest.raises(FileNotFoundError, match=missing):
        analyze("unused.mov")


def test_failed_decoding_or_bad_output_never_becomes_clean_verdict():
    with pytest.raises(RuntimeError):
        convert_output(
            {
                "status": "failed",
                "verdict": "no_violation",
                "violations": [],
                "error": "no frames decoded",
            }
        )
    with pytest.raises(ValueError):
        convert_output(
            {"status": "done", "verdict": "no_violation", "violations": [event("door_open")]}
        )
    with pytest.raises(KeyError):
        convert_output(
            {
                "status": "done",
                "verdict": "violation",
                "violations": [{**event("door_open"), "type": "unknown"}],
            }
        )
    assert (
        convert_output({"status": "done", "verdict": "no_violation", "violations": []})[
            "detections"
        ]
        == []
    )


def test_source_rules_preserve_door_and_safe_minimum_durations():
    signals = [
        {
            "t": i * 0.5,
            "people": 1,
            "cash": False,
            "cash_boxes": [],
            "bag": False,
            "laptop_on": False,
            "door_open": True,
            "safe_open": True,
        }
        for i in range(19)
    ]
    assert {kind for kind, index in Analyzer.rules(signals)} == {"door_open", "safe_open"}
    short = signals[:9]  # Four seconds does not satisfy either duration.
    assert Analyzer.rules(short) == []
