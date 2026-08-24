import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class GroupCreate(BaseModel):
    name: str
    parent_group_id: uuid.UUID | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    parent_group_id: uuid.UUID | None = None


class GroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    parent_group_id: uuid.UUID | None
    name: str
    created_at: datetime
