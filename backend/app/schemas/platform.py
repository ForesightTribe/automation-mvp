from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class PlatformStatus(BaseModel):
    """One marketplace connection, as the Connections screen needs to show it.

    Three separate facts that are easy to confuse, so they are separate fields:
    whether we hold CREDENTIALS (who to log in as), whether we hold a live
    SESSION (we are logged in now), and whether the platform is WIRED at all
    (its authenticator exists). A client can have credentials and no session,
    which is the normal state before the first login and after an expiry.
    """

    platform: str
    name: str
    wired: bool
    needs_password: bool

    connected: bool
    connected_at: datetime | None = None

    has_credentials: bool = False
    login_email: str | None = None
    has_password: bool = False
    credentials_updated_at: datetime | None = None


class PlatformCredentialsIn(BaseModel):
    """Write-only. Nothing here is ever returned by a read endpoint.

    `password` is optional because both Blinkit dashboards are passwordless —
    possession of the forwarding mailbox is the whole credential. Sending it for
    a platform that does not need one is accepted and ignored by the
    authenticator rather than rejected, so a client filling in every box cannot
    lock themselves out of a save.
    """

    email: EmailStr
    password: str | None = Field(default=None, min_length=1, max_length=256)
