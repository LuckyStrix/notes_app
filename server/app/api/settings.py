import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from ollama import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.config import settings as app_config
from app.db import get_db
from app.jobs.backup import run_media_sync_job, run_scheduled_db_backup
from app.models.settings import AppSettings
from app.queue import DEFAULT_RETRY, job_queue
from app.schemas.settings import SettingsRead, SettingsUpdate
from app.services import backup

router = APIRouter(prefix="/settings", tags=["settings"])


async def _get_singleton(db: AsyncSession) -> AppSettings:
    row = await db.get(AppSettings, 1)
    if not row:
        row = AppSettings(id=1)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def _to_read(row: AppSettings) -> SettingsRead:
    return SettingsRead(
        app_name=row.app_name,
        llm_provider=row.llm_provider,
        ollama_chat_model=row.ollama_chat_model,
        ollama_fast_model=row.ollama_fast_model,
        anthropic_chat_model=row.anthropic_chat_model,
        has_anthropic_api_key=bool(row.anthropic_api_key),
        embedding_model=row.embedding_model,
        ollama_vision_model=row.ollama_vision_model,
        whisper_model=row.whisper_model,
        whisper_language=row.whisper_language,
        whisper_idle_unload_seconds=row.whisper_idle_unload_seconds,
        default_rag_top_k=row.default_rag_top_k,
        default_rag_similarity_floor=row.default_rag_similarity_floor,
        num_ctx=row.num_ctx,
        backup_enabled=row.backup_enabled,
        backup_frequency=row.backup_frequency,
        backup_keep=row.backup_keep,
        updated_at=row.updated_at,
    )


@router.get("", response_model=SettingsRead)
async def get_settings(db: AsyncSession = Depends(get_db)):
    row = await _get_singleton(db)
    return _to_read(row)


@router.put("", response_model=SettingsRead)
async def update_settings(payload: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    row = await _get_singleton(db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return _to_read(row)


@router.get("/ollama-models")
async def list_ollama_models():
    """Models currently pulled on the host Ollama install, for the Settings
    UI's model picker -- distinct from the fixed recommendation table, since
    what's actually available depends on what the user has pulled.
    """
    client = AsyncClient(host=app_config.ollama_base_url)
    try:
        response = await client.list()
    except Exception as exc:  # noqa: BLE001 -- surface any connectivity issue to the UI
        raise HTTPException(status_code=502, detail=f"Could not reach Ollama at {app_config.ollama_base_url}: {exc}")

    return [
        {
            "name": m.model,
            "parameter_size": m.details.parameter_size if m.details else None,
            "quantization": m.details.quantization_level if m.details else None,
            "size_bytes": m.size,
        }
        for m in response.models
    ]


@router.get("/database-size")
async def get_database_size(db: AsyncSession = Depends(get_db)):
    """On-disk size of the whole database -- a rough proxy for how big an
    export will be, without actually having to run one to find out."""
    size_bytes = (await db.execute(text("SELECT pg_database_size(current_database())"))).scalar_one()
    return {"size_bytes": size_bytes}


@router.get("/database-export")
async def export_database():
    """Streams a full `pg_dump` of the database as a downloadable .sql file --
    an on-demand, UI-triggered alternative to a manual
    `docker compose exec postgres pg_dump ...` backup. Distinct from the
    managed backups below: nothing is kept server-side, and nothing is pruned."""
    try:
        args, env = backup.pg_dump_command()
    except backup.BackupError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    process = await asyncio.create_subprocess_exec(
        *args, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    async def stream():
        assert process.stdout
        try:
            while True:
                chunk = await process.stdout.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            # Headers (200 OK) are already sent by the time any of this runs,
            # so a failure here can't be turned into a clean HTTP error --
            # the best that's possible is a truncated download plus a log line.
            returncode = await process.wait()
            if returncode != 0 and process.stderr:
                stderr = (await process.stderr.read()).decode(errors="replace")
                print(f"pg_dump failed (exit {returncode}): {stderr}")

    filename = f"notes_app_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.sql"
    return StreamingResponse(
        stream(),
        media_type="application/sql",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/backups")
async def list_backups():
    """Every managed backup, newest first, plus how the last run of each kind
    went. The server only ever reads /backups; the worker writes it."""
    return await run_in_threadpool(backup.list_backups)


@router.post("/backups/run")
async def run_backup_now():
    """Runs a database backup right now, regardless of the schedule. The work
    happens in the worker, so this returns as soon as it is queued."""
    job = job_queue.enqueue(run_scheduled_db_backup, "manual", retry=DEFAULT_RETRY)
    return {"job_id": job.id, "kind": "db"}


@router.post("/backups/media")
async def run_media_backup_now():
    """Syncs the referenced media files into backups/media -- only what is new
    or changed since last time. Manual only: the first run is several GB, which
    is why nothing schedules it."""
    job = job_queue.enqueue(run_media_sync_job, retry=DEFAULT_RETRY, job_timeout=7200)
    return {"job_id": job.id, "kind": "media"}
