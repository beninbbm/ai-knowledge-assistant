"""Groups let a document be shared with a whole team at once.
Any signed-in user can list groups (to pick one when sharing); only admins manage them."""

import uuid

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.auth.users import CurrentSuperuser, CurrentUser
from app.db import SessionDep
from app.models import Group, GroupMember, User
from app.schemas import GroupCreate, GroupMemberAdd, GroupRead, MemberRead

router = APIRouter(prefix="/groups", tags=["groups"])


async def _get_group(session: SessionDep, group_id: uuid.UUID) -> Group:
    group = await session.get(Group, group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


@router.get("")
async def list_groups(user: CurrentUser, session: SessionDep) -> list[GroupRead]:
    return [
        GroupRead.model_validate(g)
        for g in await session.scalars(select(Group).order_by(Group.name))
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_group(
    body: GroupCreate, admin: CurrentSuperuser, session: SessionDep
) -> GroupRead:
    group = Group(name=body.name.strip())
    session.add(group)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="A group with that name exists"
        ) from None
    return GroupRead.model_validate(group)


@router.get("/{group_id}/members")
async def list_members(
    group_id: uuid.UUID, admin: CurrentSuperuser, session: SessionDep
) -> list[MemberRead]:
    await _get_group(session, group_id)
    users = await session.scalars(
        select(User)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
        .order_by(User.email)
    )
    return [MemberRead.model_validate(u) for u in users]


@router.post("/{group_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    group_id: uuid.UUID, body: GroupMemberAdd, admin: CurrentSuperuser, session: SessionDep
) -> MemberRead:
    await _get_group(session, group_id)
    member = await session.scalar(select(User).where(User.email == body.email.lower()))
    if member is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if await session.get(GroupMember, (group_id, member.id)) is None:
        session.add(GroupMember(group_id=group_id, user_id=member.id))
        await session.commit()
    return MemberRead.model_validate(member)


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    group_id: uuid.UUID, user_id: uuid.UUID, admin: CurrentSuperuser, session: SessionDep
) -> Response:
    await session.execute(
        delete(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
