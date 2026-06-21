"""Client-scoped platform connections. Mounted under /clients/{client_id}/platforms.

Connecting a session is interactive (OTP/browser) and done via the CLI; here we
expose connection status and disconnect.
"""
from fastapi import APIRouter, HTTPException, status

from app.dependencies import ClientDep, SessionDep
from app.schemas.platform import PlatformStatus
from app.services import platform_service

router = APIRouter()


@router.get("", response_model=list[PlatformStatus])
async def list_platforms(session: SessionDep, client: ClientDep):
    rows = await platform_service.list_sessions(session, client.id)
    return [
        PlatformStatus(platform=r.platform, connected=True, connected_at=r.updated_at)
        for r in rows
    ]


@router.delete("/{platform}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(session: SessionDep, client: ClientDep, platform: str):
    ok = await platform_service.disconnect(
        session, tenant_id=client.id, platform=platform
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No session for this platform",
        )
    return None
