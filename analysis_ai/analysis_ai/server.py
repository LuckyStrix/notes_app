"""Web service for analysis_ai.

Serves the UI and a small JSON API. Like the CLI, it only ever *reads* the notes
app (via notes_api.NotesAPI, which can only GET). Anything expensive -- Whisper,
study-card extraction, roll-ups, indexing -- happens only as a job someone
explicitly submitted; the one automatic thing is the cheap read-only sync.

No login, by design: like the notes app, it is meant to sit behind your tailnet.
State-changing requests must be application/json, which browsers won't send
cross-origin without a CORS preflight this server never grants -- so a random
web page can't make your browser trigger jobs.
"""
import contextlib
import json
import threading
import time
import urllib.error
import urllib.request
import uuid

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import chat, config, jobs, ollama, pipeline, status, store, sync, transcribe
from .notes_api import NotesAPI

STATIC = config.PACKAGE_ROOT / "web" / "static"
MAX_IDS = 500


# ---- helpers -----------------------------------------------------------------
def _uuid(value) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise HTTPException(404, "not found")


async def _json(request: Request):
    if "application/json" not in request.headers.get("content-type", ""):
        raise HTTPException(415, "Content-Type must be application/json")
    try:
        return await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "invalid JSON")


def _require_json_header(request: Request) -> None:
    if "application/json" not in request.headers.get("content-type", ""):
        raise HTTPException(415, "Content-Type must be application/json")


async def _on_http_error(request: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


# ---- sync (the only automatic behaviour) ---------------------------------------
_sync_lock = threading.Lock()
sync_state = {"running": False, "last_ok_at": None, "last_error": None, "last_result": None}


def do_sync() -> dict:
    cfg = config.load()
    with _sync_lock:
        sync_state["running"] = True
        try:
            result = sync.sync(NotesAPI(cfg["notes_api_url"]))
            sync_state.update(last_ok_at=time.time(), last_error=None, last_result=result)
        except Exception as exc:  # noqa: BLE001 -- notes app being down must not crash the tool
            sync_state["last_error"] = f"{type(exc).__name__}: {exc}"
        finally:
            sync_state["running"] = False
    return dict(sync_state)


def _sync_loop() -> None:
    while True:
        cfg = config.load()
        if cfg["auto_sync"]:
            do_sync()
        time.sleep(max(30, cfg["sync_interval_seconds"]))


manager: jobs.JobManager | None = None


def _startup() -> None:
    global manager
    store.ensure_dirs()
    manager = jobs.JobManager(pipeline.run)
    threading.Thread(target=_sync_loop, name="auto-sync", daemon=True).start()


@contextlib.asynccontextmanager
async def _lifespan(app):
    _startup()
    yield


# ---- endpoints -----------------------------------------------------------------
async def index_page(request: Request):
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


async def ping(request: Request):
    return JSONResponse({"ok": True, "service": "analysis_ai"})


def _status_payload() -> dict:
    cfg = config.load()
    return {
        "overview": status.overview(cfg),
        "jobs": manager.list(),
        "sync": dict(sync_state),
        "models": cfg["models"],
        "whisper": {"model": cfg["whisper_model"], "language": cfg["whisper_language"], "mode": transcribe.mode(cfg)},
    }


async def api_status(request: Request):
    return JSONResponse(await run_in_threadpool(_status_payload))


async def api_sync(request: Request):
    _require_json_header(request)
    return JSONResponse(await run_in_threadpool(do_sync))


def _probe(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=3):
            return {"ok": True}
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "error": str(getattr(exc, "reason", exc))}


def _health_payload() -> dict:
    cfg = config.load()
    return {"ollama": _probe(cfg["ollama_url"].rstrip("/") + "/api/tags"),
            "notes_app": _probe(cfg["notes_api_url"].rstrip("/") + "/health")}


async def api_health(request: Request):
    return JSONResponse(await run_in_threadpool(_health_payload))


def _job_title(kind: str, notes_by_id: dict, ids, project) -> str:
    if kind == "transcribe":
        if ids and len(ids) == 1:
            return f"Transcribe: {notes_by_id[ids[0]]['title']}"
        return f"Transcribe {len(ids) if ids else 'all pending'} recording(s)"
    if kind == "extract":
        if ids and len(ids) == 1:
            return f"Build study card: {notes_by_id[ids[0]]['title']}"
        return f"Build study cards{' for ' + project['name'] if project else ''}"
    if kind == "rollup":
        return f"Class overview{': ' + project['name'] if project else 's'}"
    if kind == "index":
        return "Update search index"
    return f"Update {project['name']}"


async def api_submit_job(request: Request):
    body = await _json(request)
    kind = body.get("kind")
    if kind not in pipeline.KINDS:
        raise HTTPException(400, f"kind must be one of {pipeline.KINDS}")
    notes = {n["id"]: n for n in sync.load_notes()}
    ids = body.get("ids")
    if ids is not None:
        if not isinstance(ids, list) or not ids or len(ids) > MAX_IDS:
            raise HTTPException(400, "ids must be a non-empty list")
        ids = [_uuid(i) for i in ids]
        missing = [i for i in ids if i not in notes]
        if missing:
            raise HTTPException(400, f"unknown note id: {missing[0]}")
    project = None
    if body.get("project_id"):
        pid = _uuid(body["project_id"])
        project = next((p for p in sync.load_projects() if p["id"] == pid), None)
        if project is None:
            raise HTTPException(400, "unknown project")
    if kind == "update" and project is None:
        raise HTTPException(400, "update needs project_id")
    if kind == "transcribe":
        if ids is not None and any(notes[i]["type"] not in ("audio", "video") for i in ids):
            raise HTTPException(400, "only audio/video notes can be transcribed")
    params = {"ids": ids, "project_id": project["id"] if project else None,
              "force": bool(body.get("force")), "stale_only": bool(body.get("stale_only"))}
    job = manager.submit(kind, _job_title(kind, notes, ids, project), params)
    return JSONResponse(job, status_code=202)


async def api_jobs(request: Request):
    return JSONResponse(manager.list())


async def api_job(request: Request):
    job = manager.get(request.path_params["job_id"])
    if job is None:
        raise HTTPException(404, "not found")
    return JSONResponse(job)


async def api_cancel_job(request: Request):
    _require_json_header(request)
    job = manager.cancel(request.path_params["job_id"])
    if job is None:
        raise HTTPException(404, "not found")
    return JSONResponse(job)


async def api_library(request: Request):
    pid = _uuid(request.path_params["pid"])
    data = await run_in_threadpool(status.library, pid)
    return JSONResponse(data or {"built": False})


def _note_detail(note_id: str) -> dict:
    note = store.read_json(store.SNAPSHOT / "notes" / f"{note_id}.json")
    if note is None:
        raise HTTPException(404, "not found")
    body = note["body"]
    detail = {
        "id": note["id"], "project_id": note["project_id"], "project": note["project"], "title": note["title"],
        "type": note["type"], "folder": "/".join(note["group_path"]),
        "body": body[:20000], "body_truncated": len(body) > 20000,
        "card": store.read_json(store.CARDS / f"{note_id}.json"),
    }
    if note["type"] in ("audio", "video"):
        t = transcribe.load(note_id)
        detail["transcript"] = None if not t else {
            "model": t.get("model"), "language": t.get("language"),
            "segments": [{"start": s["start"], "text": s["text"]} for s in t["segments"]],
        }
    return detail


async def api_note(request: Request):
    return JSONResponse(await run_in_threadpool(_note_detail, _uuid(request.path_params["nid"])))


async def api_chat(request: Request):
    body = await _json(request)
    message = body.get("message")
    if not isinstance(message, str) or not message.strip() or len(message) > 4000:
        raise HTTPException(400, "message must be 1-4000 characters")
    names = [p["name"] for p in sync.load_projects()]
    scope = body.get("projects") or names
    if not isinstance(scope, list) or any(s not in names for s in scope):
        raise HTTPException(400, "unknown class in projects")
    mode = body.get("mode", "strict")
    if mode not in chat.OUTSIDE:
        raise HTTPException(400, "mode must be strict or open")
    history = []
    for h in (body.get("history") or [])[-8:]:
        if not isinstance(h, dict) or h.get("role") not in ("user", "assistant") or not isinstance(h.get("content"), str):
            raise HTTPException(400, "bad history entry")
        history.append({"role": h["role"], "content": h["content"][:20000]})

    task = body.get("task")
    if task:
        if not isinstance(task, dict) or task.get("kind") not in chat.TASKS:
            raise HTTPException(400, "unknown task")
        n = task.get("n")
        if n is not None and (isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= 50):
            raise HTTPException(400, "n must be 1-50")
        request_text, query, k = chat.task_request(task["kind"], n, str(task.get("topic") or "")[:300])
    else:
        request_text, query, k = message.strip(), chat.follow_up_query(history, message.strip()), None

    cfg = config.load()

    def stream():
        def line(obj):
            return (json.dumps(obj, ensure_ascii=False) + "\n").encode()

        try:
            gen = chat.answer(cfg, scope, history, request_text, query=query, mode=mode, k=k)
            try:
                while True:
                    yield line({"type": "delta", "text": next(gen)})
            except StopIteration as stop:
                full, passages = stop.value
            yield line({"type": "sources", "sources": chat.sources_payload(passages, full)})
        except Exception as exc:  # noqa: BLE001 -- show the failure in the chat instead of a dead stream
            yield line({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store"})


def _settings_payload() -> dict:
    cfg = config.load()
    try:
        models = [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1),
                   "params": (m.get("details") or {}).get("parameter_size")} for m in ollama.list_models(cfg)]
        error = None
    except (urllib.error.URLError, OSError) as exc:
        models, error = [], str(getattr(exc, "reason", exc))
    return {
        "settings": {k: cfg[k] for k in config.EDITABLE},
        "whisper_models": config.WHISPER_MODELS,
        "ollama_models": models, "ollama_error": error,
    }


async def api_settings(request: Request):
    return JSONResponse(await run_in_threadpool(_settings_payload))


async def api_save_settings(request: Request):
    body = await _json(request)
    try:
        await run_in_threadpool(config.save_editable, body)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse(await run_in_threadpool(_settings_payload))


app = Starlette(
    routes=[
        Route("/", index_page),
        Route("/api/ping", ping),
        Route("/api/status", api_status),
        Route("/api/health", api_health),
        Route("/api/sync", api_sync, methods=["POST"]),
        Route("/api/jobs", api_jobs),
        Route("/api/jobs", api_submit_job, methods=["POST"]),
        Route("/api/jobs/{job_id}", api_job),
        Route("/api/jobs/{job_id}/cancel", api_cancel_job, methods=["POST"]),
        Route("/api/projects/{pid}/library", api_library),
        Route("/api/notes/{nid}", api_note),
        Route("/api/chat", api_chat, methods=["POST"]),
        Route("/api/settings", api_settings),
        Route("/api/settings", api_save_settings, methods=["PUT"]),
        Mount("/static", StaticFiles(directory=str(STATIC)), name="static"),
    ],
    exception_handlers={HTTPException: _on_http_error},
    lifespan=_lifespan,
)
