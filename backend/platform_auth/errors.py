"""Typed auth failures.

Callers need to tell "the session died, re-authenticate" apart from "the login
attempt itself failed" — the first is routine and self-healing, the second needs
a human. Before this module both arrived as bare RuntimeErrors with prose
messages, so nothing could react to either. `jobs.error='auth_expired'` was a
comment in app/models/job.py that nothing ever set; SessionExpired is what makes
it true.
"""


# Exit code a CLI run uses when it dies because a platform session could not be
# established. Jobs run as subprocesses, so a typed exception in the child cannot
# reach the runner — only an exit code can. jobs/runner.py maps this to
# `jobs.error='auth_expired'`, making auth failures filterable in Cloud Logging
# instead of hiding among anonymous exit_1s. 3 is unused by the CLI and outside
# the shell's reserved range.
AUTH_EXPIRED_EXIT_CODE = 3


class AuthError(Exception):
    """Base for everything in this package."""


class SessionExpired(AuthError):
    """A stored session is no longer valid. Recoverable: log in again."""

    def __init__(self, platform: str, detail: str = ""):
        self.platform = platform
        self.detail = detail
        super().__init__(f"{platform} session expired" + (f": {detail}" if detail else ""))


class NoSession(AuthError):
    """No session stored at all for this tenant/platform — never logged in."""

    def __init__(self, platform: str, tenant_id: str):
        self.platform = platform
        self.tenant_id = tenant_id
        super().__init__(
            f"No {platform} session for tenant {tenant_id}. "
            f"Run: python -m cli auth login {platform} --tenant {tenant_id}"
        )


class LoginFailed(AuthError):
    """The login flow ran but did not produce a session. Needs a human."""


class SecretNotFound(AuthError):
    """The inbox reader did not find the magic link / OTP in time."""

    def __init__(self, platform: str, timeout: float):
        super().__init__(
            f"No {platform} login email arrived within {timeout:.0f}s. "
            "Check that forwarding to the auth inbox is still active."
        )


class UnknownPlatform(AuthError):
    def __init__(self, slug: str, known: list[str]):
        super().__init__(f"Unknown platform {slug!r}. Known: {', '.join(sorted(known))}")


class PlatformNotWired(AuthError):
    """Registered as a placeholder but has no implementation yet.

    Deliberate: selecting Zepto before its authenticator exists fails loudly
    instead of silently authenticating against something else.
    """

    def __init__(self, slug: str):
        super().__init__(f"Platform {slug!r} is registered but not implemented yet.")
