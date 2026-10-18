from types import SimpleNamespace

from backend.app import analyzer as analyzer_module
from backend.app.analyzer import analyze
from backend.app.db import Store
from backend.app.worker import process_job


def test_plugin_progress_is_optional_and_forwarded(monkeypatch, tmp_path):
    progress = []

    def plugin(path, *, on_progress, duration):
        assert duration == 10
        on_progress(0.5)
        return {"detections": []}

    monkeypatch.setattr(
        analyzer_module,
        "importlib",
        SimpleNamespace(import_module=lambda name: SimpleNamespace(run=plugin)),
    )
    assert (
        analyze(tmp_path / "v.mov", "plugin", "example:run", 10, progress.append).detections == []
    )
    assert progress == [0.5]

    def legacy(path):
        return {"detections": []}

    monkeypatch.setattr(
        analyzer_module,
        "importlib",
        SimpleNamespace(import_module=lambda name: SimpleNamespace(run=legacy)),
    )
    assert (
        analyze(tmp_path / "v.mov", "plugin", "example:run", 10, progress.append).detections == []
    )


def test_worker_persists_monotonic_frame_progress(monkeypatch, tmp_path):
    settings = SimpleNamespace(
        db_path=tmp_path / "jobs.sqlite3", mode="plugin", plugin="example:run"
    )
    store = Store(settings.db_path)
    store.initialize()
    store.create("job", "video.mov", tmp_path / "video.mov", "plugin", 6)
    store.claim()
    updates = []
    save_progress = Store.progress

    def record(self, job_id, stage, value):
        save_progress(self, job_id, stage, value)
        updates.append((stage, self.get(job_id)["progress"]))

    def model(path, mode, plugin, duration, on_progress):
        for fraction in [0, 0.25, 0.25, 0.1, 0.5, 0.75, 1]:
            on_progress(fraction)
        return SimpleNamespace(detections=[], limitations=[])

    monkeypatch.setattr(Store, "progress", record)
    monkeypatch.setattr(
        "backend.app.worker.inspect_video", lambda path: SimpleNamespace(duration=10)
    )
    monkeypatch.setattr("backend.app.worker.analyze", model)
    process_job(settings, "job")
    assert updates == [
        ("analyzing", 20),
        ("analyzing", 35),
        ("analyzing", 50),
        ("analyzing", 65),
        ("analyzing", 80),
        ("extracting_evidence", 80),
    ]
    assert store.get("job")["state"] == "done"
    assert store.get("job")["progress"] == 100
