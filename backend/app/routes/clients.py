"""Client endpoints — list the account's clients and resolve the active one."""
import uuid

from fastapi import APIRouter

from app.dependencies import AccountDep, ClientDep, SessionDep
from app.schemas.client import ClientOut
from app.services import client_service

router = APIRouter()


@router.get("", response_model=list[ClientOut])
async def list_clients(session: SessionDep, account_id: AccountDep):
    """All clients under the caller's account (powers the client-switcher)."""
    return await client_service.list_clients(session, uuid.UUID(account_id))


@router.get("/{client_id}", response_model=ClientOut)
async def get_client(client: ClientDep):
    """A single client — ClientDep already enforced it belongs to the account."""
    return client
