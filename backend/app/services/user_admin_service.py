"""Managing an account's users — roles and which Clients each may see.

⚠️ Every function here takes the CALLER's account id and refuses to touch a user
outside it. Without that an admin of one account could edit another's users,
which would be a worse hole than the one client scoping exists to close. The
account id comes from the verified token, never from the request body.

Guard rails, in order of how badly they bite:

* An admin cannot drop their own admin role, and the last admin of an account
  cannot be demoted or deactivated. Either would leave the account with no one
  able to reach Settings — unrecoverable from the UI, CLI-only to fix.
* A Client can only be granted if it belongs to the same account.
* Deactivation rather than deletion. `visible_client_ids` already treats an
  inactive user as seeing nothing, so it takes effect immediately, and the row
  stays for the audit trail.
"""
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.core.security import hash_password, verify_password
from app.models.tenant import Tenant, User, UserClient
from app.services import auth_service

ROLES = ("admin", "member")
MIN_PASSWORD = 8


class UserAdminError(Exception):
    """A refusal the caller should see as a 400, not a 500."""


async def _get_in_account(
    session: AsyncSession, user_id: uuid.UUID, account_id: uuid.UUID
) -> User:
    user = await session.get(User, user_id)
    if user is None or user.account_id != account_id:
        # Same answer for "no such user" and "another account's user", so the
        # response never confirms that an id exists elsewhere.
        raise UserAdminError("User not found")
    return user


async def _admin_count(session: AsyncSession, account_id: uuid.UUID) -> int:
    rows = (
        await session.execute(
            select(User.id).where(
                User.account_id == account_id,
                User.role == "admin",
                User.is_active.is_(True),
            )
        )
    ).scalars().all()
    return len(rows)


async def list_users(session: AsyncSession, *, account_id: uuid.UUID) -> list[dict]:
    """Every user on the account with their role, scope and granted Clients."""
    users = (
        await session.execute(
            select(User).where(User.account_id == account_id).order_by(User.created_at)
        )
    ).scalars().all()
    names = dict(
        (
            await session.execute(
                select(Tenant.id, Tenant.name).where(Tenant.account_id == account_id)
            )
        ).all()
    )
    grants: dict[uuid.UUID, list[uuid.UUID]] = {}
    for row in (
        await session.execute(
            select(UserClient.user_id, UserClient.tenant_id).where(
                UserClient.user_id.in_([u.id for u in users] or [uuid.uuid4()])
            )
        )
    ).all():
        grants.setdefault(row[0], []).append(row[1])

    out = []
    for u in users:
        ids = grants.get(u.id, [])
        out.append({
            "id": u.id,
            "email": u.email,
            "full_name": u.full_name,
            "role": u.role,
            "is_active": u.is_active,
            "client_scope": u.client_scope,
            # Only meaningful for scope='listed'; empty for 'all', where the
            # user reaches every Client regardless of what rows exist.
            "clients": (
                [{"id": i, "name": names.get(i, str(i))} for i in ids]
                if u.client_scope == "listed"
                else []
            ),
            "created_at": u.created_at,
        })
    return out


async def create_user(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    email: str,
    full_name: str,
    password: str,
    role: str,
    client_ids: list[uuid.UUID] | None = None,
) -> dict:
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        raise UserAdminError("A valid email is required")
    if role not in ROLES:
        raise UserAdminError(f"Role must be one of {', '.join(ROLES)}")
    if len(password or "") < MIN_PASSWORD:
        raise UserAdminError(f"Password must be at least {MIN_PASSWORD} characters")

    existing = (
        await session.execute(select(User.id).where(User.email == email))
    ).scalars().first()
    if existing:
        raise UserAdminError("A user with that email already exists")

    user = await auth_service.create_user(
        session,
        account_id=account_id,
        email=email,
        password=password,
        full_name=(full_name or "").strip() or email.split("@")[0],
        role=role,
    )
    await session.commit()
    # Scope through set_clients so grants have ONE writer: it owns the
    # account-ownership check and the 'listed' bookkeeping.
    if client_ids is not None:
        await set_clients(
            session,
            account_id=account_id,
            user_id=user.id,
            client_ids=client_ids,
        )
    return {"id": user.id, "email": user.email}


async def set_role(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    acting_user_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> None:
    if role not in ROLES:
        raise UserAdminError(f"Role must be one of {', '.join(ROLES)}")
    user = await _get_in_account(session, user_id, account_id)
    if user.role == role:
        return
    if role != "admin":
        if user.id == acting_user_id:
            raise UserAdminError(
                "You cannot remove your own admin role — ask another admin"
            )
        if user.role == "admin" and await _admin_count(session, account_id) <= 1:
            raise UserAdminError(
                "This is the account's only admin; promote someone else first"
            )
    user.role = role
    session.add(user)
    await session.commit()


async def set_active(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    acting_user_id: uuid.UUID,
    user_id: uuid.UUID,
    is_active: bool,
) -> None:
    user = await _get_in_account(session, user_id, account_id)
    if not is_active:
        if user.id == acting_user_id:
            raise UserAdminError("You cannot deactivate your own login")
        if user.role == "admin" and await _admin_count(session, account_id) <= 1:
            raise UserAdminError("This is the account's only active admin")
    user.is_active = is_active
    session.add(user)
    await session.commit()


async def set_clients(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    client_ids: list[uuid.UUID] | None,
) -> None:
    """Scope a user to specific Clients, or to all of them.

    `client_ids=None` means scope='all'. A list means scope='listed' and
    replaces any previous grants outright, so the result is the user's complete
    access rather than an addition to it. An empty list is refused: a 'listed'
    user with nothing granted can open nothing, which is almost always a
    mistake rather than an intention.
    """
    user = await _get_in_account(session, user_id, account_id)

    if client_ids is None:
        user.client_scope = "all"
        await session.execute(delete(UserClient).where(UserClient.user_id == user.id))
        session.add(user)
        await session.commit()
        return

    if not client_ids:
        raise UserAdminError(
            "Select at least one client, or give this user access to all of them"
        )

    owned = set(
        (
            await session.execute(
                select(Tenant.id).where(Tenant.account_id == account_id)
            )
        ).scalars().all()
    )
    unknown = [c for c in client_ids if c not in owned]
    if unknown:
        # A grant outside the account would punch straight through the account
        # wall, so this is a refusal rather than a silent filter.
        raise UserAdminError("One or more clients do not belong to this account")

    await session.execute(delete(UserClient).where(UserClient.user_id == user.id))
    user.client_scope = "listed"
    for cid in dict.fromkeys(client_ids):
        session.add(UserClient(user_id=user.id, tenant_id=cid))
    session.add(user)
    await session.commit()


async def change_own_password(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    current_password: str,
    new_password: str,
) -> None:
    """A user changing their own password, proving they know the old one.

    The current password is required even though the caller is already
    authenticated: a token can be lying around on a shared machine, and without
    this check anyone holding one could lock the real owner out.
    """
    if len(new_password or "") < MIN_PASSWORD:
        raise UserAdminError(f"New password must be at least {MIN_PASSWORD} characters")
    user = await session.get(User, user_id)
    if user is None:
        raise UserAdminError("User not found")
    if not verify_password(current_password or "", user.hashed_password):
        raise UserAdminError("Current password is incorrect")
    if verify_password(new_password, user.hashed_password):
        raise UserAdminError("New password must be different from the current one")
    user.hashed_password = hash_password(new_password)
    session.add(user)
    await session.commit()


async def reset_password(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    user_id: uuid.UUID,
    new_password: str,
) -> None:
    """An admin setting someone else's password, for the locked-out case.

    No current password, because the point is that nobody has it. Shared out of
    band like a new user's, since there is no transactional email here.
    """
    if len(new_password or "") < MIN_PASSWORD:
        raise UserAdminError(f"Password must be at least {MIN_PASSWORD} characters")
    user = await _get_in_account(session, user_id, account_id)
    user.hashed_password = hash_password(new_password)
    session.add(user)
    await session.commit()


async def delete_user(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    acting_user_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    """Remove a login permanently. Prefer deactivation — this cannot be undone.

    `user_clients` rows go with it (ON DELETE CASCADE), so no grant is left
    pointing at a user that no longer exists.
    """
    user = await _get_in_account(session, user_id, account_id)
    if user.id == acting_user_id:
        raise UserAdminError("You cannot delete your own login")
    if user.role == "admin" and user.is_active and await _admin_count(session, account_id) <= 1:
        raise UserAdminError("This is the account's only active admin")
    await session.execute(delete(UserClient).where(UserClient.user_id == user.id))
    await session.delete(user)
    await session.commit()
