import base64
import time
from dataclasses import replace

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app

KEY = "test-key-at-least-16-chars"
HEADERS = {"X-API-Key": KEY}


@pytest.fixture
def settings(tmp_path):
    return Settings(api_key=KEY, data_dir=tmp_path / "data", mode="demo", serve_frontend=False)


@pytest.fixture
def video(tmp_path, request):
    path = tmp_path / "sample.mov"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (96, 64))
    assert writer.isOpened()
    for index in range(getattr(request, "param", 2) * 10):
        frame = np.zeros((64, 96, 3), dtype=np.uint8)
        frame[:, :, index % 3] = index * 10 % 256
        writer.write(frame)
    writer.release()
    return path.read_bytes()


def submit(client, video, name="sample.mov"):
    response = client.post(
        "/api/v1/analyze", headers=HEADERS, files={"file": (name, video, "video/quicktime")}
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def wait(client, job_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in {"done", "failed"}:
            return job
        time.sleep(0.05)
    pytest.fail("Job did not terminate")


def test_jury_contract_real_mov_and_jpeg(settings, video):
    with TestClient(create_app(settings)) as client:
        job_id = submit(client, video, "../../not-a-path.MOV")
        job = wait(client, job_id)
        assert job["status"] == "done", job
        assert job["verdict"] == "violation"
        assert job["mode"] == "demo"
        assert len(job["violations"]) == 1  # The two-second fixture cannot contain a 4s event.
        assert any("DEMO" in value for value in job["limitations"])
        item = job["violations"][0]
        assert item["rule"]["section"] == "пункт 19, подпункт 2"
        assert "adilet.zan.kz" in item["description"]
        frame = item["evidence_frames"][0]
        jpeg = base64.b64decode(frame["image_base64"], validate=True)
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        assert decoded is not None
        assert decoded.shape == (64, 96, 3)
        assert frame["timestamp_sec"] == pytest.approx(1.0)
        files = list((settings.data_dir / "uploads").iterdir())
        assert len(files) == 1 and files[0].name == f"{job_id}.mov"
    # Completed results survive application restart.
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json() == job


@pytest.mark.parametrize("video", [6], indirect=True)
def test_demo_returns_second_episode_at_four_seconds(settings, video):
    with TestClient(create_app(settings)) as client:
        job = wait(client, submit(client, video))
        assert job["status"] == "done", job
        assert job["mode"] == "demo"
        assert [item["timecode_sec"] for item in job["violations"]] == [1.0, 4.0]
        second = job["violations"][1]
        assert second["type"] == "Пересчёт после ухода клиента"
        assert second["confidence"] == 0
        assert second["evidence_frames"][0]["timestamp_sec"] == pytest.approx(4.0)
        jpeg = base64.b64decode(second["evidence_frames"][0]["image_base64"], validate=True)
        assert cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR) is not None


def test_service_returns_all_six_types_with_jpegs(settings, video):
    config = replace(
        settings, mode="plugin", plugin="backend.tests.model_fixtures:service_candidates"
    )
    with TestClient(create_app(config)) as client:
        job = wait(client, submit(client, video))
        assert job["status"] == "done", job
        assert job["verdict"] == "violation" and len(job["violations"]) == 6
        assert {v["rule"]["id"] for v in job["violations"]} == {
            "ML02",
            "ML03",
            "ML04",
            "ML05",
            "ML06",
            "ML07",
        }
        for item in job["violations"]:
            assert "confidence" not in item and "start_sec" not in item
            assert len(item["evidence_frames"]) == 2
            for frame in item["evidence_frames"]:
                jpeg = base64.b64decode(frame["image_base64"], validate=True)
                assert cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR) is not None


def test_auth_before_file_parsing_and_all_api_routes(settings):
    with TestClient(create_app(settings, start_worker=False)) as client:
        for path in ["/api/v1/capabilities", "/api/v1/rules", "/api/v1/jobs/unknown"]:
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"X-API-Key": "wrong"}).status_code == 401
        assert client.post("/api/v1/analyze", content=b"not multipart").status_code == 401
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/v1/jobs/unknown", headers=HEADERS).status_code == 404
        assert client.get("/api/v1/ready", headers=HEADERS).status_code == 503
        assert client.get("/api/v1/rules", headers=HEADERS).status_code == 200
        assert client.get("/api/v1/typo", headers=HEADERS).status_code == 404
        schema = client.get("/openapi.json").json()
        assert "APIKeyHeader" in schema["components"]["securitySchemes"]


def test_upload_validation_and_no_leftovers(settings):
    with TestClient(
        create_app(replace(settings, max_upload_bytes=4), start_worker=False)
    ) as client:
        for filename, payload, status in [
            ("test.exe", b"x", 415),
            ("test.mov", b"", 422),
            ("test.mov", b"12345", 413),
        ]:
            response = client.post(
                "/api/v1/analyze", headers=HEADERS, files={"file": (filename, payload)}
            )
            assert response.status_code == status, response.text
        assert list((settings.data_dir / "uploads").iterdir()) == []


def test_streamed_body_limit(settings):
    with TestClient(
        create_app(replace(settings, max_upload_bytes=4), start_worker=False)
    ) as client:
        boundary = "boundary"

        def chunks():
            yield (
                f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                'filename="sample.mov"\r\nContent-Type: video/quicktime\r\n\r\n'
            ).encode()
            for _ in range(18):
                yield b"a" * 65536
            yield f"\r\n--{boundary}--\r\n".encode()

        response = client.post(
            "/api/v1/analyze",
            content=chunks(),
            headers={**HEADERS, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        assert response.status_code == 413, response.text
        assert list((settings.data_dir / "uploads").iterdir()) == []


def test_invalid_video_is_failed_not_no_violation(settings):
    with TestClient(create_app(settings)) as client:
        job = wait(client, submit(client, b"this is not a video"))
        assert job["status"] == "failed"
        assert job["error"]["code"] == "invalid_video"
        assert "verdict" not in job


def test_missing_model_is_not_silently_demo(settings, video):
    config = replace(settings, mode="plugin", plugin="nonexistent_forte_module:analyze")
    with TestClient(create_app(config)) as client:
        assert (
            client.get("/api/v1/capabilities", headers=HEADERS).json()["model_available"] is False
        )
        response = client.post(
            "/api/v1/analyze", headers=HEADERS, files={"file": ("sample.mov", video)}
        )
        assert response.status_code == 503
        assert list((settings.data_dir / "uploads").iterdir()) == []


@pytest.mark.parametrize(
    "adapter,verdict,count",
    [
        ("no_detections", "no_violation", 0),
        ("multiple", "violation", 2),
    ],
)
def test_plugin_results(settings, video, adapter, verdict, count):
    config = replace(settings, mode="plugin", plugin=f"backend.tests.model_fixtures:{adapter}")
    with TestClient(create_app(config)) as client:
        job = wait(client, submit(client, video))
        assert job["status"] == "done", job
        assert job["verdict"] == verdict
        assert len(job["violations"]) == count
        assert job["mode"] == "plugin"
        if count:
            assert len(job["violations"][0]["evidence_frames"]) == 2
            assert job["violations"][0]["start_sec"] == 0.1
            assert job["violations"][0]["end_sec"] == 0.6
            assert "start_sec" not in job["violations"][1]


@pytest.mark.parametrize("video", [6], indirect=True)
def test_ml_rule_candidates_include_ranges_sources_and_jpegs(settings, video):
    config = replace(settings, mode="plugin", plugin="backend.tests.model_fixtures:ml_candidates")
    with TestClient(create_app(config)) as client:
        job = wait(client, submit(client, video))
        assert job["status"] == "done", job
        assert job["verdict"] == "violation" and job["mode"] == "plugin"
        assert {item["rule"]["id"] for item in job["violations"]} == {"ML01", "ML02"}
        for item in job["violations"]:
            assert (item["start_sec"], item["end_sec"]) == (0.2, 4.0)
            assert item["rule"]["verification_status"].startswith("Не подтверждено")
            assert "confidence" not in item
            assert len(item["evidence_frames"]) == 2
            for frame in item["evidence_frames"]:
                image = np.frombuffer(base64.b64decode(frame["image_base64"]), np.uint8)
                assert cv2.imdecode(image, cv2.IMREAD_COLOR) is not None


@pytest.mark.parametrize(
    "adapter,code",
    [
        ("wrong_time", "invalid_model_output"),
        ("unknown_rule", "invalid_model_output"),
        ("wrong_evidence", "invalid_model_output"),
        ("range_outside_video", "invalid_model_output"),
        ("broken", "analysis_failed"),
    ],
)
def test_bad_model_cannot_produce_a_clean_verdict(settings, video, adapter, code):
    config = replace(settings, mode="plugin", plugin=f"backend.tests.model_fixtures:{adapter}")
    with TestClient(create_app(config)) as client:
        job = wait(client, submit(client, video))
        assert job["status"] == "failed", job
        assert job["error"]["code"] == code
        assert "verdict" not in job
        assert "Private model failure" not in job["error"]["message"]


def test_timeout_kills_worker_and_next_job_is_processed(settings, video):
    config = replace(
        settings, mode="plugin", plugin="backend.tests.model_fixtures:hangs", job_timeout=1.5
    )
    with TestClient(create_app(config)) as client:
        job = wait(client, submit(client, video))
        assert job["status"] == "failed"
        assert job["error"]["code"] == "timeout"
        next_job = wait(client, submit(client, video))
        assert next_job["error"]["code"] == "timeout"
        assert client.get("/health").status_code == 200


def test_capacity_and_recovery(settings, video):
    config = replace(settings, max_pending=1)
    app = create_app(config, start_worker=False)
    with TestClient(app) as client:
        job_id = submit(client, video)
        response = client.post(
            "/api/v1/analyze", headers=HEADERS, files={"file": ("other.mov", video)}
        )
        assert response.status_code == 429
        assert len(list((settings.data_dir / "uploads").iterdir())) == 1
        app.state.store.claim()
    with TestClient(create_app(config, start_worker=False)) as client:
        job = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()
        assert job["status"] == "failed"
        assert job["error"]["code"] == "interrupted"


def test_shutdown_terminates_active_analysis(settings, video):
    config = replace(settings, mode="plugin", plugin="backend.tests.model_fixtures:hangs")
    with TestClient(create_app(config)) as client:
        job_id = submit(client, video)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()["stage"] == "analyzing":
                break
            time.sleep(0.05)
    with TestClient(create_app(config, start_worker=False)) as client:
        job = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()
        assert job["status"] == "failed"


def test_api_only_without_frontend_build_and_cors(settings):
    with TestClient(create_app(settings, start_worker=False)) as client:
        page = client.get("/")
        assert page.status_code == 404
        assert "React frontend is not built" in page.json()["detail"]
        assert client.get("/demo").status_code == 404
        response = client.options(
            "/api/v1/analyze",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key",
            },
        )
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_second_server_cannot_recover_active_jobs(settings, video):
    with TestClient(create_app(settings, start_worker=False)) as client:
        job_id = submit(client, video)
        with pytest.raises(RuntimeError, match="Another backend"):
            with TestClient(create_app(settings, start_worker=False)):
                pass
        job = client.get(f"/api/v1/jobs/{job_id}", headers=HEADERS).json()
        assert job["status"] == "processing"


def test_queued_deadline_expires_while_worker_is_busy(settings, video):
    config = replace(
        settings, mode="plugin", plugin="backend.tests.model_fixtures:hangs", job_timeout=10
    )
    app = create_app(config)
    with TestClient(app) as client:
        active = submit(client, video)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if app.state.store.get(active)["state"] == "running":
                break
            time.sleep(0.05)
        queued = submit(client, video)
        with app.state.store.connection() as conn:
            conn.execute("UPDATE jobs SET created=? WHERE id=?", (time.time() - 11, queued))
        job = wait(client, queued, timeout=2)
        assert job["error"]["code"] == "timeout"
        assert app.state.store.get(active)["state"] == "running"
