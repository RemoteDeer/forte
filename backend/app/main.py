import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader
from starlette.concurrency import run_in_threadpool

from .analyzer import plugin_available
from .config import ROOT, Settings
from .db import QueueFull, Store, iso_time
from .middleware import GuardMiddleware
from .rules import catalog
from .schemas import JobAccepted, JobResponse, Rule
from .supervisor import supervise

logger = logging.getLogger(__name__)
key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_app(settings: Settings | None = None, *, start_worker: bool = True) -> FastAPI:
    settings = settings or Settings.from_env()
    store = Store(settings.db_path)

    @asynccontextmanager
    async def lifespan(app):
        with store.runtime_lock():
            store.initialize()
            (settings.data_dir / "uploads").mkdir(parents=True, exist_ok=True)
            store.recover()
            task = asyncio.create_task(supervise(settings, store)) if start_worker else None
            try:
                yield
            finally:
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task

    app = FastAPI(
        title="ForteBank Video Analysis API",
        version="0.1.0",
        lifespan=lifespan,
        description="Локальный анализ видео. DEMO — только проверка интеграции, без ML-выводов.",
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.store = store
    app.state.settings = settings
    app.add_middleware(
        GuardMiddleware, api_key=settings.api_key, max_bytes=settings.max_upload_bytes
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["X-API-Key", "Content-Type"],
    )

    def availability():
        return settings.mode == "demo" or plugin_available(settings.plugin)

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/capabilities", dependencies=[Security(key_header)], tags=["service"])
    def capabilities():
        return {
            "mode": settings.mode,
            "model_available": availability(),
            "requires_model_validation": True,
            "max_upload_bytes": settings.max_upload_bytes,
            "accepted_extensions": [".mov", ".mp4", ".m4v", ".avi"],
            "job_timeout_sec": settings.job_timeout,
            "pending_jobs": store.pending(),
            "warning": "DEMO: тестовые результаты, модель не запускалась."
            if settings.mode == "demo"
            else "Качество определяется подключённой локальной моделью.",
        }

    @app.get("/api/v1/ready", dependencies=[Security(key_header)], tags=["service"])
    def ready():
        if settings.mode != "plugin" or not availability():
            raise HTTPException(503, "Для сдачи требуется подключённый локальный ML-модуль.")
        return {"status": "ready", "note": "Проверьте модель на контрольном видео перед сдачей."}

    @app.get(
        "/api/v1/rules",
        response_model=list[Rule],
        dependencies=[Security(key_header)],
        tags=["rules"],
    )
    def rules():
        return list(catalog().values())

    @app.post(
        "/api/v1/analyze",
        status_code=202,
        response_model=JobAccepted,
        dependencies=[Security(key_header)],
        tags=["analysis"],
    )
    async def submit(file: Annotated[UploadFile, File(description="Video (.mov), up to 500 MB")]):
        path = None
        created = False
        try:
            extension = Path(file.filename or "").suffix.lower()
            if extension not in {".mov", ".mp4", ".m4v", ".avi"}:
                raise HTTPException(415, "Поддерживаются .mov, .mp4, .m4v и .avi.")
            if not availability():
                raise HTTPException(
                    503,
                    "ML-модель или её зависимости недоступны. Проверьте веса и установку ML. "
                    "Для проверки интеграции "
                    "явно включите FORTE_ANALYZER_MODE=demo.",
                )
            if store.pending() >= settings.max_pending:
                raise HTTPException(
                    429, "Очередь заполнена. Повторите запрос позже.", headers={"Retry-After": "10"}
                )
            job_id = uuid.uuid4().hex
            path = settings.data_dir / "uploads" / f"{job_id}{extension}"
            size = 0
            # Disk operations run outside the API event loop.
            with path.open("xb") as output:
                while chunk := await file.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise HTTPException(413, "Файл превышает допустимый размер.")
                    await run_in_threadpool(output.write, chunk)
            if size == 0:
                raise HTTPException(422, "Пустой видеофайл.")
            try:
                store.create(
                    job_id, Path(file.filename).name, path, settings.mode, settings.max_pending
                )
            except QueueFull as exc:
                raise HTTPException(
                    429, "Очередь заполнена.", headers={"Retry-After": "10"}
                ) from exc
            created = True
            return JobAccepted(job_id=job_id)
        finally:
            await file.close()
            if path is not None and not created:
                path.unlink(missing_ok=True)

    @app.get(
        "/api/v1/jobs/{job_id}",
        response_model=JobResponse,
        response_model_exclude_none=True,
        dependencies=[Security(key_header)],
        tags=["analysis"],
    )
    def get_job(job_id: str):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(404, "Задание не найдено.")
        result = json.loads(job["result"]) if job["result"] else {}
        return {
            "job_id": job["id"],
            "status": {
                "queued": "processing",
                "running": "processing",
                "done": "done",
                "failed": "failed",
            }[job["state"]],
            "stage": job["stage"],
            "progress": job["progress"],
            "mode": job["mode"],
            "created_at": iso_time(job["created"]),
            "updated_at": iso_time(job["updated"]),
            "error": json.loads(job["error"]) if job["error"] else None,
            **result,
        }

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "API endpoint not found")
        dist = (ROOT / "website" / "dist").resolve()
        if settings.serve_frontend and (dist / "index.html").is_file():
            target = (dist / path).resolve()
            if target.is_relative_to(dist) and target.is_file():
                return FileResponse(target)
            # SPA routes have no extension; missing assets should remain 404.
            if not Path(path).suffix:
                return FileResponse(dist / "index.html")
        if not path:
            raise HTTPException(
                404,
                "React frontend is not built. Open http://localhost:5173 during development "
                "or run npm run build in website/.",
            )
        raise HTTPException(404, "Not found")

    return app
