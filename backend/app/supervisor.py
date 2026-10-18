import asyncio
import logging
import os
import signal
import sys
import time

from .config import ROOT, Settings
from .db import Store

logger = logging.getLogger(__name__)


async def stop_process(process):
    if process.returncode is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    await process.wait()


async def supervise(settings: Settings, store: Store):
    async with asyncio.TaskGroup() as group:
        group.create_task(_expire_waiting(settings, store))
        group.create_task(_process_queue(settings, store))


async def _expire_waiting(settings: Settings, store: Store):
    # Keep enforcing queued deadlines while a long-running model occupies the worker.
    while True:
        store.expire_queued(settings.job_timeout)
        await asyncio.sleep(0.25)


async def _process_queue(settings: Settings, store: Store):
    while True:
        store.expire_queued(settings.job_timeout)
        job = store.claim()
        if job is None:
            await asyncio.sleep(0.25)
            continue
        process = None
        try:
            remaining = settings.job_timeout - (time.time() - job["created"])
            if remaining <= 0:
                store.fail(job["id"], "timeout", "Истекло время ожидания анализа.")
                continue
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "backend.app.worker",
                job["id"],
                cwd=ROOT,
                env=settings.worker_env(),
                **({"start_new_session": True} if os.name == "posix" else {}),
            )
            await asyncio.wait_for(process.wait(), timeout=remaining)
            if store.get(job["id"])["state"] == "running":
                store.fail(
                    job["id"], "worker_crashed", "Процесс анализа завершился без результата."
                )
        except TimeoutError:
            if process:
                await stop_process(process)
            store.fail(job["id"], "timeout", "Превышено время обработки видео.")
        except asyncio.CancelledError:
            if process:
                await stop_process(process)
            store.fail(job["id"], "interrupted", "Сервис остановлен во время анализа.")
            raise
        except Exception:
            logger.exception("Worker launch failed for job %s", job["id"])
            if process:
                await stop_process(process)
            store.fail(job["id"], "worker_failed", "Не удалось запустить процесс анализа.")
