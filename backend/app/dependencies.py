"""Shared FastAPI dependencies (the DI / middleware layer).

Import the `*Dep` Annotated aliases into routes for clean signatures, e.g.:

    @router.get("/")
    async def handler(session: SessionDep, user: CurrentUserDep):
        ...
"""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import decode_token

# --- Database session -------------------------------------------------------

SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --- Authentication ---------------------------------------------------------

bearer = HTTPBearer()


class CurrentUser(BaseModel):
    user_id: str
    tenant_id: str
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
    tenant_id = payload.get("tenant_id")
    if not sub or not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token",
        )
    return CurrentUser(user_id=sub, tenant_id=tenant_id, email=payload.get("email"))


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


async def get_tenant_id(user: CurrentUserDep) -> str:
    """The tenant seam for multi-tenant isolation.

    Private/first-party endpoints depend on this and pass the result into the
    service layer so queries are always scoped to the caller's tenant.
    """
    return user.tenant_id


TenantDep = Annotated[str, Depends(get_tenant_id)]


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
