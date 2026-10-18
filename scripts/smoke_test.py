"""Exercise the jury API over HTTP without printing keys or evidence data."""

import argparse
import base64
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from html.parser import HTMLParser
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


class FrontendAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.paths.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("href"):
            self.paths.append(attrs["href"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--video", type=Path, help="Video to send to the specified service")
    parser.add_argument("--require-real", action="store_true", help="Reject demonstration mode")
    parser.add_argument("--expected-verdict", choices=["violation", "no_violation"])
    parser.add_argument("--check-frontend", action="store_true", help="Check built UI and assets")
    parser.add_argument("--job-id", help="Check an existing job, e.g. after a server restart")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    key = os.environ.get("FORTE_API_KEY", "")
    if not key:
        raise SystemExit("Set FORTE_API_KEY or create .env using scripts/init_env.py")

    def request(path, body=None, content_type=None):
        headers = {"X-API-Key": key}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(args.url.rstrip("/") + path, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"HTTP {exc.code}: {detail}") from exc

    for auth in (None, "incorrect-deployment-test-key"):
        headers = {"X-API-Key": auth} if auth else {}
        req = urllib.request.Request(args.url.rstrip("/") + "/api/v1/capabilities", headers=headers)
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise SystemExit(
                    f"Expected HTTP 401 for invalid credentials, got {exc.code}"
                ) from exc
        else:
            raise SystemExit("API unexpectedly accepted missing or incorrect credentials")
    assert request("/health") == {"status": "ok"}
    print("PASS: health and API authentication")

    if args.check_frontend:
        # Only request same-origin build assets; do not forward API keys to external URLs.
        base = args.url.rstrip("/")
        with urllib.request.urlopen(base + "/", timeout=15) as response:
            assert response.headers.get_content_type() == "text/html"
            html = response.read().decode()
        assert 'id="root"' in html and key not in html
        assets = FrontendAssets()
        assets.feed(html)
        assert assets.paths, "Built frontend has no scripts or stylesheets"
        for path in assets.paths:
            assert path.startswith("/assets/") and not path.startswith("//"), path
            with urllib.request.urlopen(base + path, timeout=15) as response:
                assert response.headers.get_content_type() != "text/html", path
                assert response.read(), f"Empty asset: {path}"
        print(f"PASS: production HTML and {len(assets.paths)} build assets")

    caps = request("/api/v1/capabilities")
    if args.require_real and caps["mode"] != "plugin":
        raise SystemExit("DEMO mode is not a real model. Set FORTE_ANALYZER_MODE=plugin.")
    if args.job_id:
        job_id = args.job_id
        print(f"Checking saved job {job_id}; mode={caps['mode']}")
    else:
        with tempfile.TemporaryDirectory(prefix="forte-smoke-") as temp:
            video = args.video
            if video is None:
                import cv2
                import numpy as np

                video = Path(temp) / "synthetic.mov"
                writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"mp4v"), 10, (96, 64))
                if not writer.isOpened():
                    raise SystemExit("Cannot create synthetic MOV")
                for index in range(60):
                    writer.write(np.full((64, 96, 3), index * 10 % 256, dtype=np.uint8))
                writer.release()
            boundary = uuid.uuid4().hex
            body = (
                (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                    f'filename="input{video.suffix}"\r\nContent-Type: video/quicktime\r\n\r\n'
                ).encode()
                + video.read_bytes()
                + f"\r\n--{boundary}--\r\n".encode()
            )
            accepted = request("/api/v1/analyze", body, f"multipart/form-data; boundary={boundary}")
            job_id = accepted["job_id"]
            print(f"Accepted job {job_id}; mode={caps['mode']}")
    deadline = time.monotonic() + 290
    while time.monotonic() < deadline:
        job = request(f"/api/v1/jobs/{job_id}")
        if job["status"] == "failed":
            raise SystemExit(f"Analysis failed: {job['error']}")
        if job["status"] == "done":
            break
        time.sleep(1)
    else:
        raise SystemExit("Polling deadline exceeded")
    verdict = job["verdict"]
    if args.require_real and job["mode"] != "plugin":
        raise SystemExit("Saved job was produced in DEMO mode; submit a new control video.")
    if args.expected_verdict and verdict != args.expected_verdict:
        raise SystemExit(f"Expected {args.expected_verdict}, got {verdict}")
    if (verdict == "violation") != bool(job["violations"]):
        raise SystemExit("Verdict and violations disagree")
    frame_count = 0
    for episode in job["violations"]:
        assert 1 <= len(episode["evidence_frames"]) <= 3
        assert episode["rule"]["url"] and episode["description"]
        for frame in episode["evidence_frames"]:
            image = base64.b64decode(frame["image_base64"], validate=True)
            assert image.startswith(b"\xff\xd8") and image.endswith(b"\xff\xd9")
            import cv2
            import numpy as np

            assert cv2.imdecode(np.frombuffer(image, np.uint8), cv2.IMREAD_COLOR) is not None
            frame_count += 1
    print(f"PASS: verdict={verdict}, episodes={len(job['violations'])}, JPEGs={frame_count}")
    if job["mode"] == "demo":
        print("DEMO only: this checks the pipeline, not detection quality.")


if __name__ == "__main__":
    main()
