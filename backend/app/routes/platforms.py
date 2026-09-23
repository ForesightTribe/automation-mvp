"""Client-scoped platform connections. Mounted under /clients/{client_id}/platforms.

The API behind Settings: what each marketplace's connection looks like, and the three
writes that change it — save the login, start a login, disconnect.

Those three are ADMIN-ONLY (`AdminDep`). A member sees connection status and the data,
and cannot connect, reconnect or disconnect. The frontend hides Settings from members as
well, but this is the wall.

Logging in is a JOB, not a request: it sends a magic link or an OTP and then waits for
that mail to reach us through the client's forwarding — seconds at best, sometimes never.
The route enqueues `auth.login` and returns its id for the screen to poll.
"""
from fastapi import APIRouter, HTTPException, status

from app.dependencies import AdminDep, ClientDep, SessionDep
from app.schemas.campaign_manager import EnqueuedOut
from app.schemas.platform import PlatformCredentialsIn, PlatformStatus
from app.services import platform_service
from jobs.queue import DuplicateActiveJob, enqueue
from platform_auth import registry

router = APIRouter()


def _known(platform: str) -> None:
    """Reject an unknown slug before anything is written under it."""
    if platform not in registry.AUTHENTICATORS:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Unknown platform {platform!r}",
        )


@router.get("", response_model=list[PlatformStatus])
async def list_platforms(session: SessionDep, client: ClientDep):
    return await platform_service.overview(session, client.id)


@router.put("/{platform}/credentials", status_code=status.HTTP_204_NO_CONTENT)
async def set_credentials(
    session: SessionDep,
    client: ClientDep,
    _admin: AdminDep,
    platform: str,
    body: PlatformCredentialsIn,
):
    """Save who to log in as. Write-only — no endpoint reads a password back.

    Deliberately allowed for a platform that is not wired yet: a client can be
    set up before we finish the authenticator, and the alternative is asking them
    to come back later for a form they have already seen.
    """
    _known(platform)
    await platform_service.save_credentials(
        session,
        tenant_id=client.id,
        platform=platform,
        email=body.email,
        password=body.password,
    )
    return None


@router.post("/{platform}/login", response_model=EnqueuedOut)
async def start_login(
    session: SessionDep, client: ClientDep, _admin: AdminDep, platform: str
):
    """Begin a login and return the job to poll.

    One login per platform at a time (409 otherwise): a login consumes a single-use
    secret, and two in flight race for the same mail.
    """
    _known(platform)
    auth = registry.AUTHENTICATORS[platform]
    if not auth.wired:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{auth.name} is not connectable yet.",
        )
    try:
        job = await enqueue(
            session,
            job_type="auth.login",
            tenant_id=client.id,
            params={"platform": platform},
        )
    except DuplicateActiveJob:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A login for this platform is already running. Give it a minute.",
        )
    return EnqueuedOut(job_id=job.id)


@router.delete("/{platform}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    session: SessionDep, client: ClientDep, _admin: AdminDep, platform: str
):
    ok = await platform_service.disconnect(
        session, tenant_id=client.id, platform=platform
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nothing to disconnect for this platform",
        )
    return None
