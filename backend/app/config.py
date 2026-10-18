import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    api_key: str
    data_dir: Path = ROOT / "data"
    mode: str = "plugin"
    plugin: str = "ml.service_inference:analyze"
    max_upload_bytes: int = 500_000_000
    job_timeout: float = 270
    max_pending: int = 6
    cors_origins: tuple[str, ...] = ("http://localhost:5173", "http://127.0.0.1:5173")
    serve_frontend: bool = True

    def __post_init__(self):
        object.__setattr__(self, "data_dir", self.data_dir.resolve())
        if len(self.api_key) < 16:
            raise ValueError(
                "FORTE_API_KEY must contain at least 16 characters; run scripts/init_env.py"
            )
        if self.mode not in {"plugin", "demo"}:
            raise ValueError("FORTE_ANALYZER_MODE must be plugin or demo")
        if not 0 < self.job_timeout <= 280:
            raise ValueError("FORTE_JOB_TIMEOUT_SEC must be in (0, 280]")
        if self.max_upload_bytes <= 0 or self.max_pending <= 0:
            raise ValueError("Upload size and queue capacity must be positive")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.sqlite3"

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env")
        return cls(
            api_key=os.getenv("FORTE_API_KEY", ""),
            data_dir=Path(os.getenv("FORTE_DATA_DIR", str(ROOT / "data"))),
            mode=os.getenv("FORTE_ANALYZER_MODE", "plugin"),
            plugin=os.getenv("FORTE_ML_CALLABLE", "ml.service_inference:analyze"),
            max_upload_bytes=int(os.getenv("FORTE_MAX_UPLOAD_BYTES", "500000000")),
            job_timeout=float(os.getenv("FORTE_JOB_TIMEOUT_SEC", "270")),
            max_pending=int(os.getenv("FORTE_MAX_PENDING_JOBS", "6")),
            cors_origins=tuple(
                x.strip()
                for x in os.getenv(
                    "FORTE_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
                ).split(",")
                if x.strip()
            ),
            serve_frontend=os.getenv("FORTE_SERVE_FRONTEND", "1") == "1",
        )

    def worker_env(self) -> dict[str, str]:
        return {
            **os.environ,
            "FORTE_API_KEY": self.api_key,
            "FORTE_DATA_DIR": str(self.data_dir),
            "FORTE_ANALYZER_MODE": self.mode,
            "FORTE_ML_CALLABLE": self.plugin,
            "FORTE_JOB_TIMEOUT_SEC": str(self.job_timeout),
            # Standard offline flags for common local model libraries.
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
