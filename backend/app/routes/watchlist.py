"""Client-scoped watchlist CRUD. Mounted under /clients/{client_id}/watchlist."""
from fastapi import APIRouter, HTTPException, status

from app.dependencies import ClientDep, SessionDep
from app.schemas.watchlist import WatchlistCreate, WatchlistEntryOut, WatchlistUpdate
from app.services import watchlist_service

router = APIRouter()


@router.get("", response_model=list[WatchlistEntryOut])
async def list_watchlist(session: SessionDep, client: ClientDep):
    return await watchlist_service.list_watchlist(session, client.id)


@router.post("", response_model=WatchlistEntryOut, status_code=status.HTTP_201_CREATED)
async def add_entry(session: SessionDep, client: ClientDep, payload: WatchlistCreate):
    if not await watchlist_service.brand_exists(session, payload.brand_slug):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown brand: {payload.brand_slug}",
        )
    return await watchlist_service.create_entry(
        session, tenant_id=client.id, data=payload
    )


@router.put("/{entry_id}", response_model=WatchlistEntryOut)
async def update_entry(
    session: SessionDep, client: ClientDep, entry_id: int, payload: WatchlistUpdate
):
    entry = await watchlist_service.get_entry_for_client(
        session, entry_id=entry_id, tenant_id=client.id
    )
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist entry not found"
        )
    return await watchlist_service.update_entry(session, entry=entry, data=payload)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(session: SessionDep, client: ClientDep, entry_id: int):
    entry = await watchlist_service.get_entry_for_client(
        session, entry_id=entry_id, tenant_id=client.id
    )
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Watchlist entry not found"
        )
    await watchlist_service.delete_entry(session, entry=entry)
    return None
