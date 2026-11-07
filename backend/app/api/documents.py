"""Document library endpoints. Uploading arrives in Phase 2; this phase covers who can
see, share and delete documents."""

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, select

from app.auth.users import CurrentUser
from app.db import SessionDep
from app.models import Document, DocumentPermission, Group, User
from app.permissions import can_read_document, get_owned_document, get_readable_document
from app.schemas import DocumentRead, DocumentShares

router = APIRouter(prefix="/documents", tags=["documents"])


def to_read(document: Document, user: User) -> DocumentRead:
    result = DocumentRead.model_validate(document)
    result.is_owner = document.owner_id == user.id
    return result


@router.get("")
async def list_documents(user: CurrentUser, session: SessionDep) -> list[DocumentRead]:
    """Every document the current user may read: their own plus those shared with them."""
    documents = await session.scalars(
        select(Document).where(can_read_document(user.id)).order_by(Document.created_at.desc())
    )
    return [to_read(d, user) for d in documents]


@router.get("/{document_id}")
async def get_document(
    document_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> DocumentRead:
    return to_read(await get_readable_document(session, user, document_id), user)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    document = await get_owned_document(session, user, document_id)
    await session.delete(document)  # permissions (and later chunks) cascade
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _current_shares(session: SessionDep, document_id: uuid.UUID) -> DocumentShares:
    rows = (
        await session.execute(
            select(User.email, DocumentPermission.group_id)
            .select_from(DocumentPermission)
            .outerjoin(User, User.id == DocumentPermission.user_id)
            .where(DocumentPermission.document_id == document_id)
        )
    ).all()
    return DocumentShares(
        user_emails=sorted(email for email, _ in rows if email),
        group_ids=[group_id for _, group_id in rows if group_id],
    )


@router.get("/{document_id}/permissions")
async def get_permissions(
    document_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> DocumentShares:
    await get_owned_document(session, user, document_id)
    return await _current_shares(session, document_id)


@router.put("/{document_id}/permissions")
async def set_permissions(
    document_id: uuid.UUID, shares: DocumentShares, user: CurrentUser, session: SessionDep
) -> DocumentShares:
    """Replace who the document is shared with. Send empty lists to make it private again."""
    await get_owned_document(session, user, document_id)

    emails = {e.lower() for e in shares.user_emails} - {user.email.lower()}  # owner is implicit
    users = (await session.scalars(select(User).where(User.email.in_(emails)))).all()
    unknown_emails = emails - {u.email.lower() for u in users}

    group_ids = set(shares.group_ids)
    found_groups = set(await session.scalars(select(Group.id).where(Group.id.in_(group_ids))))
    unknown_groups = group_ids - found_groups

    if unknown_emails or unknown_groups:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "unknown_user_emails": sorted(unknown_emails),
                "unknown_group_ids": sorted(str(g) for g in unknown_groups),
            },
        )

    await session.execute(
        delete(DocumentPermission).where(DocumentPermission.document_id == document_id)
    )
    session.add_all(
        [DocumentPermission(document_id=document_id, user_id=u.id) for u in users]
        + [DocumentPermission(document_id=document_id, group_id=g) for g in group_ids]
    )
    await session.commit()
    return await _current_shares(session, document_id)
