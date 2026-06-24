"""Auth endpoints. Login-only — accounts/users are provisioned via the CLI."""
import uuid

from fastapi import APIRouter, HTTPException, status

from app.core.security import create_access_token
from app.dependencies import CurrentUserDep, SessionDep
from app.schemas.auth import LoginRequest, TokenResponse, UserOut
from app.services import auth_service

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, session: SessionDep):
    user = await auth_service.authenticate(session, payload.email, payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
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
