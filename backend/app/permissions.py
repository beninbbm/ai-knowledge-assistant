"""The single source of truth for "who can read which document".

Every code path that returns document content (listing, search, chat retrieval, source
passages, file downloads) must go through this module. Keeping the rule in one place is
what stops permission leaks as the app grows.

Rules:
- The owner can read, share and delete their document.
- Users granted access directly, or through a group they belong to, can read it.
- Anyone else gets 404 Not Found (not 403) so they can't even learn the document exists.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import ColumnElement, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, DocumentPermission, GroupMember, User


def can_read_document(user_id: uuid.UUID) -> ColumnElement[bool]:
    """A SQL condition, usable in any query that involves `Document`, that is true only
    for documents this user may read. Example:

        select(Document).where(can_read_document(user.id))
    """
    users_groups = select(GroupMember.group_id).where(GroupMember.user_id == user_id)
    shared_with_user = exists().where(
        DocumentPermission.document_id == Document.id,
        or_(
            DocumentPermission.user_id == user_id,
            DocumentPermission.group_id.in_(users_groups),
        ),
    )
    return or_(Document.owner_id == user_id, shared_with_user)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")


async def get_readable_document(
    session: AsyncSession, user: User, document_id: uuid.UUID
) -> Document:
    """Load a document the user may read, or raise 404."""
    document = await session.scalar(
        select(Document).where(Document.id == document_id, can_read_document(user.id))
    )
    if document is None:
        raise _not_found()
    return document


async def get_owned_document(session: AsyncSession, user: User, document_id: uuid.UUID) -> Document:
    """Load a document the user owns (needed to share or delete it).

    404 if they can't read it at all; 403 if they can read it but aren't the owner
    (they already know it exists, so there is nothing to hide)."""
    document = await get_readable_document(session, user, document_id)
    if document.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the document's owner can do this",
        )
    return document
