import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    # Sending `null` explicitly clears the override back to "inherit the
    # global default" -- exclude_unset in the API handler means an omitted
    # field leaves the existing value alone, same as every other field here.
    rag_top_k: int | None = Field(default=None, ge=1, le=50)
    rag_similarity_floor: float | None = Field(default=None, ge=0, le=1)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    rag_top_k: int | None
    rag_similarity_floor: float | None
    position: int
    graph_status: str
    graph_error: str | None
    graph_updated_at: datetime | None
    summary_generation_status: str
    summary_generation_error: str | None
    summary_generation_progress: int
    summary_generation_total: int
    created_at: datetime
    updated_at: datetime
