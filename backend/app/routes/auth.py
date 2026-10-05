"""Auth endpoints. Login-only — accounts/users are provisioned via the CLI."""
import math
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.core.config import settings
from app.core.security import create_access_token
from app.utils import ratelimit
from app.utils.logger import logger
from app.dependencies import CurrentUserDep, SessionDep
from app.schemas.auth import LoginRequest, TokenResponse, UserOut
from app.services import auth_service

router = APIRouter()


def _retry_phrase(seconds: float) -> str:
    """How long is left, rounded up, so "1 minute" never means "still locked"."""
    if seconds < 60:
        return "less than a minute"
    minutes = math.ceil(seconds / 60)
    return "1 minute" if minutes == 1 else f"{minutes} minutes"


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: SessionDep, request: Request):
    """Exchange email + password for a bearer token.

    Rate limited on failures, per email and per client IP (see
    `app/utils/ratelimit.py`). A locked identity gets 429 + `Retry-After`
    BEFORE the password is checked, so a lockout also stops the bcrypt work —
    which is the expensive part and, on a single worker, the cheaper way to
    hurt this API than guessing the password.
    """
    email = (payload.email or "").strip().lower()
    ip = ratelimit.client_ip(request)
    window = float(settings.LOGIN_WINDOW_SECONDS)

    if settings.LOGIN_MAX_PER_EMAIL:
        for bucket, identity, limit in (
            ("email", email, settings.LOGIN_MAX_PER_EMAIL),
            ("ip", ip, settings.LOGIN_MAX_PER_IP),
        ):
            wait = ratelimit.check(bucket, identity, limit, window)
            if wait is not None:
                logger.warning(
                    "login blocked by rate limit: {}={} retry_after={}s",
                    bucket, identity, int(wait) + 1,
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=(
                        "Too many failed sign-in attempts. "
                        f"Try again in {_retry_phrase(wait)}."
                    ),
                    headers={"Retry-After": str(int(wait) + 1)},
                )

    user = await auth_service.authenticate(session, payload.email, payload.password)
    if not user:
        # Both buckets, so neither a single IP spraying many accounts nor many
        # IPs targeting one account slips between them.
        ratelimit.record_failure("email", email, window)
        ratelimit.record_failure("ip", ip, window)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    ratelimit.clear("email", email)
    token = create_access_token(
        {
            "sub": str(user.id),
            "account_id": str(user.account_id),
            "email": user.email,
            "role": user.role,
        }
    )
    return TokenResponse(access_token=token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout():
    # Stateless JWT: the client just discards the token. Endpoint kept for
    # symmetry and to give the frontend a clear hook.
    return None


@router.get("/me", response_model=UserOut)
async def me(session: SessionDep, current: CurrentUserDep):
    user = await auth_service.get_user_by_id(session, uuid.UUID(current.user_id))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    return user
