"""Account user management — ADMIN ONLY, and only within the caller's account.

Mounted under /account/users. Account-scoped rather than client-scoped: a user
belongs to the account, not to one of its Clients, so these do not take a
{client_id}. The account id comes from the verified token.
"""
import uuid

from fastapi import APIRouter, HTTPException, status

from app.dependencies import AdminDep, SessionDep
from app.schemas.user_admin import (
    AccountUserOut,
    CreateUserIn,
    CreateUserOut,
    ResetPasswordIn,
    SetActiveIn,
    SetClientsIn,
    SetRoleIn,
)
from app.services import user_admin_service as svc
from app.services.user_admin_service import UserAdminError

router = APIRouter()


def _bad(e: UserAdminError):
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("", response_model=list[AccountUserOut])
async def list_users(session: SessionDep, admin: AdminDep):
    """Everyone on this account, with their role and client access."""
    return await svc.list_users(session, account_id=uuid.UUID(admin.account_id))


@router.post("", response_model=CreateUserOut, status_code=201)
async def create_user(session: SessionDep, admin: AdminDep, body: CreateUserIn):
    """Add a login to this account. The password is shared out of band."""
    try:
        return await svc.create_user(
            session,
            account_id=uuid.UUID(admin.account_id),
            email=body.email,
            full_name=body.full_name,
            password=body.password,
            role=body.role,
            client_ids=body.client_ids,
        )
    except UserAdminError as e:
        raise _bad(e)


@router.patch("/{user_id}/role", status_code=204)
async def set_role(
    session: SessionDep, admin: AdminDep, user_id: uuid.UUID, body: SetRoleIn
):
    try:
        await svc.set_role(
            session,
            account_id=uuid.UUID(admin.account_id),
            acting_user_id=uuid.UUID(admin.user_id),
            user_id=user_id,
            role=body.role,
        )
    except UserAdminError as e:
        raise _bad(e)


@router.patch("/{user_id}/active", status_code=204)
async def set_active(
    session: SessionDep, admin: AdminDep, user_id: uuid.UUID, body: SetActiveIn
):
    """Deactivate or restore a login. Deactivation closes access at once —
    `visible_client_ids` treats an inactive user as seeing nothing."""
    try:
        await svc.set_active(
            session,
            account_id=uuid.UUID(admin.account_id),
            acting_user_id=uuid.UUID(admin.user_id),
            user_id=user_id,
            is_active=body.is_active,
        )
    except UserAdminError as e:
        raise _bad(e)


@router.put("/{user_id}/clients", status_code=204)
async def set_clients(
    session: SessionDep, admin: AdminDep, user_id: uuid.UUID, body: SetClientsIn
):
    """Which Clients this user may see. Replaces any previous grants.

    ⚠️ Takes up to `CLIENT_CHECK_TTL_S` (60s) to bite on a running API process,
    which caches passed access checks per user.
    """
    try:
        await svc.set_clients(
            session,
            account_id=uuid.UUID(admin.account_id),
            user_id=user_id,
            client_ids=body.client_ids,
        )
    except UserAdminError as e:
        raise _bad(e)


@router.post("/{user_id}/password", status_code=204)
async def reset_password(
    session: SessionDep, admin: AdminDep, user_id: uuid.UUID, body: ResetPasswordIn
):
    """Set someone else's password, for when they cannot sign in."""
    try:
        await svc.reset_password(
            session,
            account_id=uuid.UUID(admin.account_id),
            user_id=user_id,
            new_password=body.new_password,
        )
    except UserAdminError as e:
        raise _bad(e)


@router.delete("/{user_id}", status_code=204)
async def delete_user(session: SessionDep, admin: AdminDep, user_id: uuid.UUID):
    """⚠️ Permanent. Deactivation is the reversible option."""
    try:
        await svc.delete_user(
            session,
            account_id=uuid.UUID(admin.account_id),
            acting_user_id=uuid.UUID(admin.user_id),
            user_id=user_id,
        )
    except UserAdminError as e:
        raise _bad(e)
