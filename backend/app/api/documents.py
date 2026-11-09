"""Document library endpoints: upload, list, view, download, share, reprocess, delete."""

import hashlib
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.auth.users import CurrentUser
from app.config import settings
from app.db import SessionDep
from app.ingestion.extractors import FileType, detect_file_type, uncompressed_size
from app.models import Document, DocumentChunk, DocumentPermission, DocumentStatus, Group, User
from app.permissions import can_read_document, get_owned_document, get_readable_document
from app.ratelimit import uploads
from app.schemas import ChunkRead, DocumentRead, DocumentShares
from app.storage import FileStorage, get_storage

router = APIRouter(prefix="/documents", tags=["documents"])

StorageDep = Annotated[FileStorage, Depends(get_storage)]


def to_read(document: Document, user: User) -> DocumentRead:
    result = DocumentRead.model_validate(document)
    result.is_owner = document.owner_id == user.id
    return result


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(uploads.dependency())])
async def upload_document(
    user: CurrentUser,
    session: SessionDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File(description="A .pdf, .docx or .md file")],
    title: Annotated[str | None, Form()] = None,
) -> DocumentRead:
    """Save the file and queue it for processing. Returns immediately with status
    "pending"; the worker extracts and chunks it in the background."""
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"File is larger than {settings.max_upload_bytes // (1024 * 1024)} MB",
        )
    filename = Path(file.filename or "upload").name[:300]
    file_type = detect_file_type(filename, data)
    if file_type is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file. Upload a PDF (.pdf), Word (.docx) or Markdown (.md) file.",
        )

    if (
        file_type == FileType.DOCX
        and uncompressed_size(data) > settings.max_docx_uncompressed_bytes
    ):
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail="This Word file expands to an unusually large size and was rejected.",
        )

    sha256 = hashlib.sha256(data).hexdigest()
    existing = await session.scalar(
        select(Document.id).where(Document.owner_id == user.id, Document.sha256 == sha256)
    )
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"message": "You already uploaded this file", "document_id": str(existing)},
        )

    document_id = uuid.uuid4()
    storage_key = f"{user.id}/{document_id}{Path(filename).suffix.lower()}"
    storage.save(storage_key, data)
    document = Document(
        id=document_id,
        owner_id=user.id,
        title=(title or "").strip()[:300] or Path(filename).stem,
        filename=filename,
        mime_type=file_type.value,
        sha256=sha256,
        storage_path=storage_key,
        size_bytes=len(data),
        status=DocumentStatus.PENDING,
    )
    session.add(document)
    try:
        await session.commit()
    except IntegrityError:  # the same file uploaded twice at the same moment
        storage.delete(storage_key)
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="You already uploaded this file"
        ) from None
    return to_read(document, user)


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
    document_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> Response:
    document = await get_owned_document(session, user, document_id)
    storage_key = document.storage_path
    await session.delete(document)  # its permissions and chunks are deleted by the database
    await session.commit()
    storage.delete(storage_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{document_id}/file")
async def download_file(
    document_id: uuid.UUID, user: CurrentUser, session: SessionDep, storage: StorageDep
) -> FileResponse:
    """The original uploaded file (used later by the PDF viewer)."""
    document = await get_readable_document(session, user, document_id)
    path = storage.path(document.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="File is missing from storage")
    return FileResponse(
        path,
        media_type=document.mime_type,
        filename=document.filename,
        content_disposition_type="inline",
    )


@router.get("/{document_id}/chunks")
async def list_chunks(
    document_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[ChunkRead]:
    """All chunks of a document, in order. Handy for seeing how a file was split."""
    await get_readable_document(session, user, document_id)
    chunks = await session.scalars(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
    )
    return [ChunkRead.model_validate(c) for c in chunks]


@router.post("/{document_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess_document(
    document_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> DocumentRead:
    """Queue the document to be extracted and chunked again (e.g. after a failure, or
    after changing chunk settings)."""
    document = await get_owned_document(session, user, document_id)
    if document.status == DocumentStatus.PROCESSING:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Document is already processing")
    document.status = DocumentStatus.PENDING
    document.error = None
    await session.commit()
    return to_read(document, user)


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
