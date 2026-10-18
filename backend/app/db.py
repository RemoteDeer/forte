import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path


def iso_time(value: float) -> str:
    return datetime.fromtimestamp(value, UTC).isoformat()


class QueueFull(Exception):
    pass


class Store:
    """SQLite is also the durable queue. One API process owns its worker."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, path TEXT NOT NULL,
                state TEXT NOT NULL, stage TEXT NOT NULL, progress INTEGER NOT NULL,
                mode TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
                result TEXT, error TEXT
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state, created)")

    def create(self, job_id, filename, path, mode, capacity):
        now = time.time()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            count = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')"
            ).fetchone()[0]
            if count >= capacity:
                raise QueueFull
            conn.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, filename, str(path), "queued", "queued", 0, mode, now, now, None, None),
            )

    def get(self, job_id):
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    @contextmanager
    def runtime_lock(self):
        """A separate SQLite lock prevents two API owners from recovering each other's jobs."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock = sqlite3.connect(self.path.with_name("service-lock.sqlite3"), timeout=0)
        try:
            try:
                lock.execute("BEGIN EXCLUSIVE")
            except sqlite3.OperationalError as exc:
                raise RuntimeError(
                    "Another backend is using this data directory. Run one Uvicorn worker."
                ) from exc
            yield
        finally:
            lock.rollback()
            lock.close()

    def claim(self):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1"
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE jobs SET state='running',stage='validating',progress=5,updated=? "
                    "WHERE id=?",
                    (time.time(), row["id"]),
                )
                return dict(row)
        return None

    def progress(self, job_id, stage, value):
        with self.connection() as conn:
            conn.execute(
                "UPDATE jobs SET stage=?,progress=?,updated=? WHERE id=? AND state='running'",
                (stage, value, time.time(), job_id),
            )

    def finish(self, job_id, result):
        with self.connection() as conn:
            conn.execute(
                """UPDATE jobs SET state='done',stage='completed',progress=100,result=?,updated=?
                   WHERE id=? AND state='running'""",
                (json.dumps(result, ensure_ascii=False), time.time(), job_id),
            )

    def fail(self, job_id, code, message):
        with self.connection() as conn:
            conn.execute(
                """UPDATE jobs SET state='failed',stage='failed',error=?,updated=?
                   WHERE id=? AND state IN ('queued','running')""",
                (json.dumps({"code": code, "message": message}), time.time(), job_id),
            )

    def recover(self):
        with self.connection() as conn:
            conn.execute(
                """UPDATE jobs SET state='failed',stage='failed',error=?,updated=?
                   WHERE state='running'""",
                (
                    json.dumps(
                        {
                            "code": "interrupted",
                            "message": "Сервис перезапущен во время анализа."
                            " Загрузите видео повторно.",
                        }
                    ),
                    time.time(),
                ),
            )

    def pending(self):
        with self.connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE state IN ('queued','running')"
            ).fetchone()[0]

    def expire_queued(self, deadline):
        with self.connection() as conn:
            conn.execute(
                """UPDATE jobs SET state='failed',stage='failed',error=?,updated=?
                   WHERE state='queued' AND created<?""",
                (
                    json.dumps({"code": "timeout", "message": "Истекло время ожидания анализа."}),
                    time.time(),
                    time.time() - deadline,
                ),
            )
