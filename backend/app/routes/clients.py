"""Client endpoints — list the account's clients and resolve the active one."""
import uuid

from fastapi import APIRouter

from app.dependencies import ClientDep, CurrentUserDep, SessionDep
from app.schemas.client import ClientOut
from app.services import client_service

router = APIRouter()


@router.get("", response_model=list[ClientOut])
async def list_clients(session: SessionDep, user: CurrentUserDep):
    """The clients this user may switch between (powers the client-switcher).

    Scoped to the user, not just the account — the same set `ClientDep` will open.
    """
    return await client_service.list_clients(
        session, uuid.UUID(user.account_id), uuid.UUID(user.user_id)
    )


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(client: ClientDep):
    """A single client — ClientDep already enforced it belongs to the account."""
    return client
