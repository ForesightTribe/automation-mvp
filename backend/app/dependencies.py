"""Shared FastAPI dependencies (the DI / middleware layer).

Import the `*Dep` Annotated aliases into routes for clean signatures, e.g.:

    @router.get("/")
    async def handler(session: SessionDep, user: CurrentUserDep):
        ...
"""
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
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
    role: str = "member"


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
    return CurrentUser(
        user_id=sub,
        account_id=account_id,
        email=payload.get("email"),
        role=payload.get("role", "member"),
    )


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]


async def require_admin(user: CurrentUserDep) -> CurrentUser:
    """Gate admin-only routes. Members get a 403. The frontend mirrors this by
    hiding admin UI, but this dependency is the real wall."""
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


AdminDep = Annotated[CurrentUser, Depends(require_admin)]


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


# --- Reporting period (the global date window) ------------------------------

@dataclass
class Period:
    """A resolved date window plus the immediately-preceding window of equal
    length, so any handler can compute period-over-period growth without
    redoing the math. `start`/`end` are inclusive calendar dates.
    """

    start: date
    end: date
    prev_start: date
    prev_end: date

    @property
    def length_days(self) -> int:
        return (self.end - self.start).days + 1


def get_period(
    start: date | None = Query(
        None, description="Window start (inclusive, YYYY-MM-DD)."
    ),
    end: date | None = Query(
        None, description="Window end (inclusive, YYYY-MM-DD)."
    ),
    days: int | None = Query(
        None, ge=1, le=365, description="Legacy: last N days ending today."
    ),
) -> Period:
    """Resolve the reporting window from either an explicit `start`/`end` range
    or the legacy `days` count (last N days ending today). `start`/`end` win if
    given; otherwise `days` (defaulting to 30) anchors the window to today. The
    previous window is the same length immediately before `start`.
    """
    if start and end:
        if end < start:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="end must not be before start",
            )
        win_start, win_end = start, end
    else:
        n = days or 30
        win_end = date.today()
        win_start = win_end - timedelta(days=n - 1)

    length = (win_end - win_start).days + 1
    return Period(
        start=win_start,
        end=win_end,
        prev_end=win_start - timedelta(days=1),
        prev_start=win_start - timedelta(days=length),
    )


PeriodDep = Annotated[Period, Depends(get_period)]


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
    limit: int = Query(20, ge=1, le=500, description="Items per page"),
) -> Pagination:
    return Pagination(page=page, limit=limit)


PaginationDep = Annotated[Pagination, Depends(get_pagination)]
