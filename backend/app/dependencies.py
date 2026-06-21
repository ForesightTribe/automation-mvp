"""Shared FastAPI dependencies (the DI / middleware layer).

Import the `*Dep` Annotated aliases into routes for clean signatures, e.g.:

    @router.get("/")
    async def handler(session: SessionDep, user: CurrentUserDep):
        ...
"""
import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import decode_token
from app.models.tenant import Tenant
from app.services import client_service

# --- Database session -------------------------------------------------------

SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --- Authentication ---------------------------------------------------------

bearer = HTTPBearer()


class CurrentUser(BaseModel):
    user_id: str
    account_id: str
    email: str | None = None


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> CurrentUser:
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    sub = payload.get("sub")
    account_id = payload.get("account_id")
    if not sub or not account_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token",
        )
    return CurrentUser(user_id=sub, account_id=account_id, email=payload.get("email"))


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


async def get_account_id(user: CurrentUserDep) -> str:
    """The account seam. The active *client* is chosen per-request (path param)
    and validated against this account before any tenant-scoped query runs.
    """
    return user.account_id


AccountDep = Annotated[str, Depends(get_account_id)]


# --- Active client (the access wall) ---------------------------------------

async def get_client(
    client_id: uuid.UUID,        # bound to the {client_id} path segment
    account_id: AccountDep,
    session: SessionDep,
) -> Tenant:
    """Resolve {client_id} from the URL, but only if it belongs to the caller's
    account. Any other client (or a bogus id) returns 404 — so one account can
    never reach another's data. Hands the route a validated Client (Tenant).
    """
    client = await client_service.get_client_for_account(
        session, client_id, uuid.UUID(account_id)
    )
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
        )
    return client


ClientDep = Annotated[Tenant, Depends(get_client)]


# --- Pagination -------------------------------------------------------------

@dataclass
class Pagination:
    page: int
    limit: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


def get_pagination(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
) -> Pagination:
    return Pagination(page=page, limit=limit)


PaginationDep = Annotated[Pagination, Depends(get_pagination)]
