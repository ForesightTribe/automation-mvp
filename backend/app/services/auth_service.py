"""Authentication + account/user provisioning.

`authenticate` / `get_user_by_id` back the API; `create_account` /
`create_user` back the CLI seed command (there is no public signup).
"""
import uuid

from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.account import Account
from app.models.tenant import User


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def get_user_by_id(session: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await session.get(User, user_id)


async def create_account(
    session: AsyncSession, *, name: str, type: str = "agency"
) -> Account:
    account = Account(name=name, type=type)
    session.add(account)
    await session.flush()  # populate account.id without committing
    return account


async def create_user(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    email: str,
    password: str,
    full_name: str,
) -> User:
    user = User(
        account_id=account_id,
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
    )
    session.add(user)
    await session.flush()
    return user
