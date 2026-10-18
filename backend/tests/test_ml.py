import sys
from types import SimpleNamespace

import pytest

from backend.app.analyzer import plugin_available
from backend.app.rules import catalog
from backend.app.schemas import ModelOutput
from ml import analyze_video, inference


class Values:
    def __init__(self, items):
        self.items = items

    def tolist(self):
        return self.items


class SceneModel:
    names = {0: "person", 1: "cash"}

    def __init__(self, people):
        self.people = people

    def predict(self, image, **kwargs):
        boxes = self.people + [[40, 40, 50, 50]]
        return [
            SimpleNamespace(
                boxes=SimpleNamespace(
                    xyxy=Values(boxes),
                    cls=Values([0] * len(self.people) + [1]),
                    conf=Values([0.9] * len(boxes)),
                )
            )
        ]


def test_detector_and_adapter_preserve_two_distinct_rule_ranges(monkeypatch):
    monkeypatch.setattr(
        analyze_video,
        "sample_frames",
        lambda path, fps: ((float(index), SimpleNamespace(size=(100, 100))) for index in range(5)),
    )
    # A person outside the default work area and exposed cash on the desk.
    progress = []
    raw = analyze_video.analyze(
        SceneModel([[0, 0, 10, 20]]),
        "unused.mov",
        duration=5,
        on_progress=progress.append,
    )
    assert progress == pytest.approx([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    output = ModelOutput.model_validate(inference.convert_output(raw))
    assert {item.rule_id for item in output.detections} == {"ML01", "ML02"}
    for item in output.detections:
        assert item.rule_id in catalog()
        assert (item.start_sec, item.timecode_sec, item.end_sec) == (0, 0, 4)
        assert item.evidence_timestamps == [0, 2]
        assert item.confidence is None  # Not an invented calibrated score.
    assert raw["used_fallback_area"]
    assert any("рабочая зона" in text for text in output.limitations)


def test_present_person_does_not_trigger_unattended_cash(monkeypatch):
    monkeypatch.setattr(
        analyze_video,
        "sample_frames",
        lambda path, fps: ((float(index), SimpleNamespace(size=(100, 100))) for index in range(5)),
    )
    raw = analyze_video.analyze(SceneModel([[30, 20, 70, 90]]), "unused.mov")
    assert raw["verdict"] == "no_violation"
    assert inference.convert_output(raw)["detections"] == []


def test_no_frames_is_failure_not_a_clean_verdict(monkeypatch):
    monkeypatch.setattr(analyze_video, "sample_frames", lambda path, fps: iter(()))
    progress = []
    with pytest.raises(ValueError, match="No frames"):
        analyze_video.analyze(SceneModel([]), "unused.mov", on_progress=progress.append)
    assert progress == []
    with pytest.raises(RuntimeError, match="no frames"):
        inference.convert_output({"error": "no frames", "violations": []})


def test_inconsistent_or_unknown_model_events_are_rejected():
    with pytest.raises(ValueError, match="disagrees"):
        inference.convert_output({"verdict": "violation", "violations": []})
    with pytest.raises(KeyError):
        inference.convert_output({"verdict": "violation", "violations": [{"kind": "unknown"}]})


def test_missing_weights_fail_preflight_without_downloading(monkeypatch, tmp_path):
    monkeypatch.setenv("FORTE_MODEL_PATH", str(tmp_path / "absent.pt"))
    assert not plugin_available("ml.inference:analyze")
    with pytest.raises(FileNotFoundError, match="weights missing"):
        inference.analyze("unused.mov")


def test_mov_timestamps_are_relative_to_first_frame(monkeypatch):
    class Container:
        streams = SimpleNamespace(video=[SimpleNamespace(time_base=0.001)])

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def decode(self, stream):
            for pts in [5000, 5400, 5800]:
                yield SimpleNamespace(pts=pts, to_image=lambda: "frame")

    monkeypatch.setitem(sys.modules, "av", SimpleNamespace(open=lambda path: Container()))
    samples = list(analyze_video.sample_frames("timestamp-offset.mov", 3))
    assert [timestamp for timestamp, image in samples] == pytest.approx([0, 0.4, 0.8])
