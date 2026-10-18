"""Run the API and Vite together; stop both when either exits or Ctrl+C is pressed."""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stop(process):
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
    elif process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()


def main():
    npm = shutil.which("npm")
    if npm is None:
        print("Node.js/npm not found. Install Node.js, then run npm ci in website/.")
        return 1
    if not (ROOT / "website/node_modules/vite/bin/vite.js").is_file():
        print("Frontend dependencies missing. Run: cd website && npm ci")
        return 1
    check = subprocess.run(
        [sys.executable, "-c", "import fastapi, uvicorn, multipart, cv2, dotenv"],
        capture_output=True,
    )
    if check.returncode:
        print("Backend dependencies missing. From the project root run:")
        print("  python3 -m venv .venv")
        print("  .venv/bin/python -m pip install -e './backend[dev]'")
        return 1
    if not (ROOT / ".env").is_file() and not os.getenv("FORTE_API_KEY"):
        print("Configuration missing. Run: python3 scripts/init_env.py --demo")
        return 1

    commands = [
        (
            "Backend",
            ROOT,
            [
                sys.executable,
                "-m",
                "uvicorn",
                "backend.app.main:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--workers",
                "1",
            ],
        ),
        (
            "Frontend",
            ROOT / "website",
            [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173", "--strictPort"],
        ),
    ]
    processes = []
    exit_code = 0

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    print("Starting frontend and backend; logs appear below.", flush=True)
    print("App: http://localhost:5173 | Backend API: http://localhost:8000/api/v1", flush=True)
    print("API docs: http://localhost:8000/docs | Ctrl+C stops both services.", flush=True)
    try:
        for name, cwd, command in commands:
            process = subprocess.Popen(command, cwd=cwd, start_new_session=os.name == "posix")
            processes.append((name, process))
        while True:
            for name, process in processes:
                code = process.poll()
                if code is not None:
                    print(f"{name} exited (code {code}). Stopping both services.", flush=True)
                    return code if code > 0 else 1
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopping frontend and backend...", flush=True)
    except OSError as exc:
        print(f"Cannot start services: {exc}", file=sys.stderr)
        exit_code = 1
    finally:
        # Ignore repeated interrupts while children perform graceful shutdown.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for _, process in reversed(processes):
            stop(process)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
