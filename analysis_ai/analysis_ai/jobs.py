"""A tiny persistent job queue for the web service.

One worker thread runs jobs strictly one at a time: every stage that matters
(Whisper, the big Ollama model) wants the whole GPU, so parallelism would only
make them slower or crash them. Jobs are cancellable at their next checkpoint
(see progress.Ctx) and survive restarts as records; a job that was running when
the service stopped is marked "interrupted" and is never silently resumed --
you press the button again, and the per-stage caches make that cheap.
"""
import threading
import traceback
import uuid
from datetime import datetime, timezone

from . import store
from .progress import Cancelled, Ctx

JOBS_FILE = store.D / "jobs.json"
KEEP_JOBS = 40
KEEP_LOG_LINES = 400


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobManager:
    def __init__(self, runner):
        self._runner = runner  # runner(kind, params, ctx) -> None
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._cancel: set[str] = set()
        self._jobs: list[dict] = store.read_json(JOBS_FILE, [])
        for job in self._jobs:
            if job["status"] in ("queued", "running"):
                job["status"] = "interrupted"
                job["finished"] = _now()
        self._persist()
        threading.Thread(target=self._loop, name="job-runner", daemon=True).start()

    # ---- public -----------------------------------------------------------
    def submit(self, kind: str, title: str, params: dict) -> dict:
        with self._lock:
            for job in self._jobs:  # pressing a button twice must not queue the work twice
                if job["status"] in ("queued", "running") and job["kind"] == kind and job["params"] == params:
                    return job
            job = {"id": uuid.uuid4().hex[:12], "kind": kind, "title": title, "params": params, "status": "queued",
                   "created": _now(), "started": None, "finished": None,
                   "progress": {"done": 0, "total": 0, "current": ""}, "log": [], "error": None}
            self._jobs.append(job)
            self._trim()
            self._persist()
        self._wake.set()
        return job

    def cancel(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._find(job_id)
            if job is None:
                return None
            if job["status"] == "queued":
                job["status"], job["finished"] = "cancelled", _now()
                self._persist()
            elif job["status"] == "running":
                self._cancel.add(job_id)
                job["log"].append("(cancel requested -- stops at the next checkpoint)")
            return job

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(j, log=j["log"][-40:]) for j in reversed(self._jobs)]

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._find(job_id)
            return dict(job) if job else None

    def busy(self) -> dict | None:
        with self._lock:
            return next((dict(j, log=[]) for j in self._jobs if j["status"] == "running"), None)

    # ---- internals --------------------------------------------------------
    def _find(self, job_id: str) -> dict | None:
        return next((j for j in self._jobs if j["id"] == job_id), None)

    def _trim(self) -> None:
        finished = [j for j in self._jobs if j["status"] not in ("queued", "running")]
        for j in finished[: max(0, len(finished) - KEEP_JOBS)]:
            self._jobs.remove(j)

    def _persist(self) -> None:
        store.write_json(JOBS_FILE, self._jobs)

    def _loop(self) -> None:
        while True:
            self._wake.wait()
            while True:
                with self._lock:
                    job = next((j for j in self._jobs if j["status"] == "queued"), None)
                    if job is None:
                        self._wake.clear()
                        break
                    job["status"], job["started"] = "running", _now()
                    self._persist()
                self._run(job)

    def _run(self, job: dict) -> None:
        def log(message: str) -> None:
            with self._lock:
                job["log"].append(message)
                del job["log"][:-KEEP_LOG_LINES]

        def progress(done: int, total: int, current: str = "") -> None:
            with self._lock:
                job["progress"] = {"done": done, "total": total, "current": current}

        ctx = Ctx(log=log, is_cancelled=lambda: job["id"] in self._cancel, on_progress=progress)
        try:
            self._runner(job["kind"], job["params"], ctx)
            status, error = "done", None
        except Cancelled:
            status, error = "cancelled", None
        except Exception as exc:  # noqa: BLE001 -- a failing job must never kill the runner thread
            status, error = "failed", str(exc)
            log("".join(traceback.format_exception_only(type(exc), exc)).strip())
        with self._lock:
            job["status"], job["error"], job["finished"] = status, error, _now()
            self._cancel.discard(job["id"])
            self._persist()
