"""Shapes of the JSON going in and out of the API (validated by Pydantic)."""

import uuid
from datetime import datetime

from fastapi_users import schemas
from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import DocumentStatus


class UserRead(schemas.BaseUser[uuid.UUID]):
    pass


class UserCreate(schemas.BaseUserCreate):
    pass


class UserUpdate(schemas.BaseUserUpdate):
    pass


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class DocumentRead(ORMModel):
    id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    filename: str
    mime_type: str
    size_bytes: int
    page_count: int | None
    status: DocumentStatus
    error: str | None
    created_at: datetime
    is_owner: bool = False


class DocumentShares(BaseModel):
    """Who a document is shared with (besides its owner). PUT replaces the whole list."""

    user_emails: list[EmailStr] = []
    group_ids: list[uuid.UUID] = []


class GroupCreate(BaseModel):
    name: str


class GroupRead(ORMModel):
    id: uuid.UUID
    name: str
    created_at: datetime


class GroupMemberAdd(BaseModel):
    email: EmailStr


class MemberRead(ORMModel):
    id: uuid.UUID
    email: str
