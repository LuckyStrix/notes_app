from fastapi import APIRouter, Depends, HTTPException
from ollama import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as app_config
from app.db import get_db
from app.models.settings import AppSettings
from app.schemas.settings import SettingsRead, SettingsUpdate

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
        anthropic_chat_model=row.anthropic_chat_model,
        has_anthropic_api_key=bool(row.anthropic_api_key),
        embedding_model=row.embedding_model,
        whisper_model=row.whisper_model,
        whisper_idle_unload_seconds=row.whisper_idle_unload_seconds,
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
