"""The contract every marketplace authenticator implements.

One shape for all marketplaces, so everything above this layer — the CLI, the
job runner, the scrapers — stays marketplace-agnostic. Adding Zepto is a new
folder under marketplaces/ plus one registry entry; nothing else changes.

Two ideas are worth stating explicitly because they drove the design:

1. **A session is not a browser storage_state.** Blinkit marketing's credential is
   a Firebase refresh token; the seller dashboard's is an opaque access/refresh
   pair. Both can be *projected* into a Playwright storage_state for consumers
   that still drive a browser, and into ready-to-send API headers for those that
   don't. `AuthSession` carries the native credential plus both projections, so a
   consumer takes whichever it needs.

2. **Login is two-phase.** Requesting the secret and consuming it are separate
   calls, because between them something has to read an inbox. Splitting them is
   also what lets the same authenticator serve both the automatic path (IMAP) and
   the manual one (a human pasting into a terminal).
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable

from app.utils.time import now_ist


class SecretKind(str, Enum):
    MAGIC_LINK = "magic_link"
    OTP = "otp"


@dataclass
class Credentials:
    """What a platform needs to BEGIN a login.

    Blinkit's two dashboards are passwordless — possession of the mailbox is the
    whole credential. Zepto uses email + password, so `password` is optional
    rather than absent, and `extra` carries anything a future marketplace needs
    (a sub-account id, a portal code) without another schema change.

    Stored per (tenant, platform) in `platform_credentials`; the password is
    Fernet-encrypted at rest, the address is not (it is PII, not a secret, and
    it must stay readable to render status without decrypting every row).
    """

    email: str
    password: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def redacted(self) -> str:
        return f"{self.email} ({'password set' if self.password else 'no password'})"


@dataclass
class LoginChallenge:
    """Handed back by start_login, consumed by complete_login.

    `requested_at` is the inbox reader's cutoff: only mail newer than this can be
    the secret we just triggered. Without it, a stale OTP from an hour ago looks
    like a valid answer.

    `credentials` rides along because some platforms need the password again at
    the completion step, not just to trigger the secret.
    """

    platform: str
    email: str
    secret_kind: SecretKind
    requested_at: datetime = field(default_factory=now_ist)
    credentials: Credentials | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthSession:
    """A live credential for one (tenant, platform), in three views."""

    platform: str
    email: str
    raw: dict[str, Any]                       # native credential — the source of truth
    storage_state: dict[str, Any] = field(default_factory=dict)  # Playwright projection
    headers: dict[str, str] = field(default_factory=dict)        # direct-API projection
    obtained_at: datetime = field(default_factory=now_ist)
    expires_at: datetime | None = None        # best-known hard expiry, if any

    def to_envelope(self) -> dict:
        return {
            "__v": 2,
            "platform": self.platform,
            "email": self.email,
            "raw": self.raw,
            "storage_state": self.storage_state,
            "headers": self.headers,
            "obtained_at": self.obtained_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }

    @classmethod
    def from_envelope(cls, data: dict) -> "AuthSession":
        """Load a stored session.

        Rows written before this module hold a bare Playwright storage_state with
        no envelope. Treat those as legacy: the storage_state IS the credential.
        """
        if data.get("__v") != 2:
            return cls(
                platform=data.get("__legacy_platform", ""),
                email="",
                raw={},
                storage_state=data,
            )
        return cls(
            platform=data["platform"],
            email=data.get("email", ""),
            raw=data.get("raw", {}),
            storage_state=data.get("storage_state", {}),
            headers=data.get("headers", {}),
            obtained_at=datetime.fromisoformat(data["obtained_at"]),
            expires_at=(
                datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
            ),
        )


# start_login(credentials) -> challenge   (triggers the email; no secret yet)
StartLogin = Callable[["Credentials"], Awaitable[LoginChallenge]]
# complete_login(challenge, secret) -> session
CompleteLogin = Callable[[LoginChallenge, str], Awaitable[AuthSession]]
# probe(session) -> is it still usable?
Probe = Callable[[AuthSession], Awaitable[bool]]
# refresh(session) -> extended session, or None if this platform can't refresh
Refresh = Callable[[AuthSession], Awaitable[AuthSession | None]]


@dataclass(frozen=True)
class Authenticator:
    """One marketplace dashboard's login, behind the common interface.

    A pure data record of callables — no behaviour of its own, exactly like
    scraper/public/providers.py::Provider.
    """

    slug: str            # matches platform_sessions.platform
    name: str            # human label
    marketplace: str     # "blinkit" | "zepto" | …  (several dashboards may share one)
    secret_kind: SecretKind
    # Whether a stored password is required to start a login. False for the
    # Blinkit dashboards (passwordless), True for Zepto.
    needs_password: bool = False
    wired: bool = False
    start_login: StartLogin | None = None
    complete_login: CompleteLogin | None = None
    probe: Probe | None = None
    refresh: Refresh | None = None
    # True when a live session can be renewed indefinitely without a new secret.
    # Both Blinkit dashboards can; a platform that can't will need periodic mail.
    refreshable: bool = False
